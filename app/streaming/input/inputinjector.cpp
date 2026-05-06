#include "inputinjector.h"

#include <Limelight.h>
#include <SDL.h>

#include <QJsonDocument>
#include <QJsonObject>

#include <algorithm>

#if defined(Q_OS_WIN)
#include <qt_windows.h>
#include <timeapi.h>
#endif

std::atomic<bool> InputInjector::sBlockPhysical{false};

InputInjector::InputInjector(QObject* parent)
    : QObject(parent)
{
}

InputInjector::~InputInjector()
{
    disable();
}

void InputInjector::enable()
{
    if (m_Enabled.load()) {
        return;
    }

    m_Stop.store(false);

    // Reserve indices 0 (P1) and 1 (P2) on the virtual side.
    m_Mask = 0x03;
    declareArrival(0);
    declareArrival(1);

    // Send an initial neutral frame for both pads so the host sees them.
    sendNeutral(0);
    sendNeutral(1);

    m_Worker = std::thread(&InputInjector::workerLoop, this);
    m_Enabled.store(true);

    SDL_LogInfo(SDL_LOG_CATEGORY_APPLICATION,
                "InputInjector: enabled (mask=0x%X)", m_Mask);
}

void InputInjector::disable()
{
    if (!m_Enabled.load()) {
        return;
    }

    {
        std::lock_guard<std::mutex> lk(m_Mtx);
        m_Stop.store(true);
        m_Queue.clear();
    }
    m_Cv.notify_all();
    if (m_Worker.joinable()) {
        m_Worker.join();
    }

    // Final neutral frames so the host doesn't see stuck buttons.
    sendNeutral(0);
    sendNeutral(1);

    m_Enabled.store(false);
    SDL_LogInfo(SDL_LOG_CATEGORY_APPLICATION, "InputInjector: disabled");
}

void InputInjector::declareArrival(int padIndex)
{
    // Declare a generic Xbox-style controller with all standard capabilities.
    // Capabilities bitfield uses LI_CCAP_* values from Limelight.h
    LiSendControllerArrivalEvent(static_cast<uint8_t>(padIndex),
                                 m_Mask,
                                 LI_CTYPE_XBOX,
                                 0,
                                 LI_CCAP_ANALOG_TRIGGERS | LI_CCAP_RUMBLE);
}

void InputInjector::sendState(int padIndex, const InjectorPadState& s)
{
    if (padIndex < 0 || padIndex > 1) return;

    LiSendMultiControllerEvent(
        static_cast<short>(padIndex),
        static_cast<short>(m_Mask),
        s.buttons,
        static_cast<unsigned char>(std::clamp(s.lt, 0, 255)),
        static_cast<unsigned char>(std::clamp(s.rt, 0, 255)),
        static_cast<short>(std::clamp(s.lsX, -32768, 32767)),
        static_cast<short>(std::clamp(s.lsY, -32768, 32767)),
        static_cast<short>(std::clamp(s.rsX, -32768, 32767)),
        static_cast<short>(std::clamp(s.rsY, -32768, 32767)));

    m_LastState[padIndex] = s;
    m_LastState[padIndex].present = true;
    m_EventsApplied.fetch_add(1);
}

void InputInjector::sendNeutral(int padIndex)
{
    InjectorPadState neutral;
    neutral.present = true;
    sendState(padIndex, neutral);
}

void InputInjector::play(double fps,
                         const QVector<InjectorEvent>& relativeEvents,
                         int shiftPad0,
                         int shiftPad1)
{
    if (!m_Enabled.load()) {
        SDL_LogWarn(SDL_LOG_CATEGORY_APPLICATION,
                    "InputInjector::play called while disabled");
        return;
    }
    if (fps <= 0.0) fps = 120.0;

    const auto now = std::chrono::steady_clock::now();
    const auto frameDur = std::chrono::microseconds(
        static_cast<int64_t>(1e6 / fps));

    {
        std::lock_guard<std::mutex> lk(m_Mtx);
        m_Queue.clear();

        // Insert one neutral frame for each pad immediately, so the new
        // sequence starts from a known state with no leftover buttons.
        InjectorEvent neutral;
        neutral.deadline = now;
        neutral.pads[0].present = true;
        neutral.pads[1].present = true;
        m_Queue.push_back(neutral);

        // The base time for the new sequence starts one frame after now,
        // so the neutral frame has time to be observed by the host.
        const auto base = now + frameDur;

        for (const auto& src : relativeEvents) {
            InjectorEvent ev = src;
            // Convert "deadline" (treated as offset from origin in us via
            // count of microseconds in time_since_epoch of relative tp) into
            // an absolute deadline. We require callers to encode the
            // per-frame offset in the .deadline field as a steady_clock
            // time_point with value = epoch + (frame * frameDur).
            const auto offset = src.deadline.time_since_epoch();

            // Apply per-pad shift: when pad i is present in this event, its
            // effective deadline is base + offset + shift_i*frameDur.
            // Because a single event can carry both pads, and shifts can
            // differ, we split it into up to two events (one per pad).
            for (int pad = 0; pad < 2; ++pad) {
                if (!src.pads[pad].present) continue;
                int shift = (pad == 0) ? shiftPad0 : shiftPad1;
                auto deadline = base
                    + std::chrono::duration_cast<std::chrono::steady_clock::duration>(offset)
                    + shift * frameDur;
                if (deadline < now) {
                    deadline = now; // truncate negative shifts that fell into the past
                    SDL_LogWarn(SDL_LOG_CATEGORY_APPLICATION,
                                "InputInjector: shift truncated for pad %d", pad);
                }
                InjectorEvent split;
                split.deadline = deadline;
                split.pads[pad] = src.pads[pad];
                split.pads[pad].present = true;
                split.pads[1 - pad].present = false;
                m_Queue.push_back(split);
            }
        }

        std::sort(m_Queue.begin(), m_Queue.end(),
                  [](const InjectorEvent& a, const InjectorEvent& b) {
                      return a.deadline < b.deadline;
                  });
    }
    m_Cv.notify_all();
}

void InputInjector::stopSequence()
{
    if (!m_Enabled.load()) return;
    {
        std::lock_guard<std::mutex> lk(m_Mtx);
        m_Queue.clear();
        InjectorEvent neutral;
        neutral.deadline = std::chrono::steady_clock::now();
        neutral.pads[0].present = true;
        neutral.pads[1].present = true;
        m_Queue.push_back(neutral);
    }
    m_Cv.notify_all();
}

void InputInjector::hold(int padIndex, const InjectorPadState& state)
{
    if (!m_Enabled.load()) return;
    if (padIndex < 0 || padIndex > 1) return;

    {
        std::lock_guard<std::mutex> lk(m_Mtx);
        m_Queue.clear();
        InjectorEvent ev;
        ev.deadline = std::chrono::steady_clock::now();
        ev.pads[padIndex] = state;
        ev.pads[padIndex].present = true;
        m_Queue.push_back(ev);
    }
    m_Cv.notify_all();
}

QString InputInjector::statusJson() const
{
    QJsonObject obj;
    obj["enabled"] = m_Enabled.load();
    {
        std::lock_guard<std::mutex> lk(m_Mtx);
        obj["queued"] = static_cast<int>(m_Queue.size());
    }
    obj["events_applied"] = static_cast<qint64>(m_EventsApplied.load());
    obj["last_drift_us"] = static_cast<qint64>(m_LastDriftUs.load());
    return QString::fromUtf8(QJsonDocument(obj).toJson(QJsonDocument::Compact));
}

void InputInjector::workerLoop()
{
#if defined(Q_OS_WIN)
    timeBeginPeriod(1);
#endif

    while (!m_Stop.load()) {
        std::unique_lock<std::mutex> lk(m_Mtx);

        if (m_Queue.empty()) {
            m_Cv.wait_for(lk, std::chrono::milliseconds(50),
                          [&]{ return m_Stop.load() || !m_Queue.empty(); });
            continue;
        }

        auto deadline = m_Queue.front().deadline;
        auto now = std::chrono::steady_clock::now();
        auto delay = deadline - now;

        if (delay > std::chrono::microseconds(1500)) {
            m_Cv.wait_for(lk, delay - std::chrono::microseconds(500));
            continue;
        }

        // Busy-wait the last ~1.5ms for sub-frame precision (lock released).
        InjectorEvent ev = m_Queue.front();
        m_Queue.erase(m_Queue.begin());
        lk.unlock();

        while (std::chrono::steady_clock::now() < ev.deadline) {
            // Spin. Worst case ~1.5ms.
        }

        auto fired = std::chrono::steady_clock::now();
        auto drift = std::chrono::duration_cast<std::chrono::microseconds>(
            fired - ev.deadline).count();
        m_LastDriftUs.store(drift);

        for (int pad = 0; pad < 2; ++pad) {
            if (ev.pads[pad].present) {
                sendState(pad, ev.pads[pad]);
            }
        }
    }

#if defined(Q_OS_WIN)
    timeEndPeriod(1);
#endif
}
