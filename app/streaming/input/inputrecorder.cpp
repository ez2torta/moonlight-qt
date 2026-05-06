#include "inputrecorder.h"

#include <Limelight.h>
#include <SDL.h>

#include <QFile>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QSaveFile>

#include <cmath>

InputRecorder* InputRecorder::s_Instance = nullptr;

namespace {
// Ordered list mirroring the bit positions used by play.py / InputControlServer.
// We only emit names for bits that are actually set, so order doesn't matter
// for replay correctness.
struct ButtonBit { int flag; const char* name; };
static const ButtonBit kButtonBits[] = {
    { A_FLAG,        "A" },
    { B_FLAG,        "B" },
    { X_FLAG,        "X" },
    { Y_FLAG,        "Y" },
    { UP_FLAG,       "UP" },
    { DOWN_FLAG,     "DOWN" },
    { LEFT_FLAG,     "LEFT" },
    { RIGHT_FLAG,    "RIGHT" },
    { LB_FLAG,       "LB" },
    { RB_FLAG,       "RB" },
    { LS_CLK_FLAG,   "LS" },
    { RS_CLK_FLAG,   "RS" },
    { BACK_FLAG,     "BACK" },
    { PLAY_FLAG,     "START" },
    { SPECIAL_FLAG,  "GUIDE" },
    { MISC_FLAG,     "MISC" },
    { PADDLE1_FLAG,  "PADDLE1" },
    { PADDLE2_FLAG,  "PADDLE2" },
    { PADDLE3_FLAG,  "PADDLE3" },
    { PADDLE4_FLAG,  "PADDLE4" },
    { TOUCHPAD_FLAG, "TOUCHPAD" },
};

QJsonArray buttonsToArray(int buttons)
{
    QJsonArray a;
    for (const auto& b : kButtonBits) {
        if ((buttons & b.flag) != 0) {
            a.append(QString::fromLatin1(b.name));
        }
    }
    return a;
}
}

InputRecorder::InputRecorder(const QString& outputPath, double frameHz, QObject* parent)
    : QObject(parent),
      m_OutputPath(outputPath),
      m_FrameHz(frameHz > 1.0 ? frameHz : 60.0)
{
}

InputRecorder::~InputRecorder()
{
    finish();
}

void InputRecorder::start()
{
    if (m_Active.load()) {
        return;
    }
    {
        std::lock_guard<std::mutex> lk(m_Mtx);
        m_Events.clear();
        for (auto& p : m_LastPad) {
            p = PadSnapshot{};
        }
        m_T0 = std::chrono::steady_clock::now();
    }
    s_Instance = this;
    m_Active.store(true);

    SDL_LogInfo(SDL_LOG_CATEGORY_APPLICATION,
                "InputRecorder: capturing to %s @ %.2f Hz",
                m_OutputPath.toUtf8().constData(), m_FrameHz);
}

void InputRecorder::finish()
{
    if (!m_Active.exchange(false)) {
        return;
    }
    s_Instance = nullptr;

    QVector<RecordedEvent> events;
    {
        std::lock_guard<std::mutex> lk(m_Mtx);
        events.swap(m_Events);
    }

    QJsonArray jsonEvents;
    for (const auto& ev : events) {
        QJsonObject pad;
        pad.insert("buttons", buttonsToArray(ev.state.buttons));
        pad.insert("lt", ev.state.lt);
        pad.insert("rt", ev.state.rt);
        pad.insert("ls_x", ev.state.lsX);
        pad.insert("ls_y", ev.state.lsY);
        pad.insert("rs_x", ev.state.rsX);
        pad.insert("rs_y", ev.state.rsY);

        QJsonObject pads;
        pads.insert(QString::number(ev.padIndex), pad);

        QJsonObject obj;
        obj.insert("frame", ev.frame);
        obj.insert("pads", pads);
        jsonEvents.append(obj);
    }

    QJsonObject root;
    root.insert("frame_hz", m_FrameHz);
    root.insert("shift_pad0", 0);
    root.insert("shift_pad1", 0);
    root.insert("events", jsonEvents);

    QSaveFile f(m_OutputPath);
    if (!f.open(QIODevice::WriteOnly | QIODevice::Truncate)) {
        SDL_LogError(SDL_LOG_CATEGORY_APPLICATION,
                     "InputRecorder: cannot open '%s' for write: %s",
                     m_OutputPath.toUtf8().constData(),
                     f.errorString().toUtf8().constData());
        return;
    }
    f.write(QJsonDocument(root).toJson(QJsonDocument::Indented));
    if (!f.commit()) {
        SDL_LogError(SDL_LOG_CATEGORY_APPLICATION,
                     "InputRecorder: commit failed: %s",
                     f.errorString().toUtf8().constData());
        return;
    }

    SDL_LogInfo(SDL_LOG_CATEGORY_APPLICATION,
                "InputRecorder: wrote %d events to %s",
                static_cast<int>(events.size()),
                QFileInfo(m_OutputPath).absoluteFilePath().toUtf8().constData());
}

void InputRecorder::tap(int padIndex, int buttons,
                        int lt, int rt,
                        int lsX, int lsY, int rsX, int rsY)
{
    InputRecorder* inst = s_Instance;
    if (inst == nullptr || !inst->m_Active.load()) {
        return;
    }
    if (padIndex < 0 || padIndex >= 16) {
        return;
    }
    inst->recordInstance(padIndex, buttons, lt, rt, lsX, lsY, rsX, rsY);
}

void InputRecorder::recordInstance(int padIndex, int buttons,
                                   int lt, int rt,
                                   int lsX, int lsY, int rsX, int rsY)
{
    std::lock_guard<std::mutex> lk(m_Mtx);

    PadSnapshot& last = m_LastPad[padIndex];
    if (last.valid &&
        last.buttons == buttons &&
        last.lt == lt && last.rt == rt &&
        last.lsX == lsX && last.lsY == lsY &&
        last.rsX == rsX && last.rsY == rsY) {
        return; // no change for this pad
    }

    last.valid = true;
    last.buttons = buttons;
    last.lt = lt; last.rt = rt;
    last.lsX = lsX; last.lsY = lsY;
    last.rsX = rsX; last.rsY = rsY;

    auto now = std::chrono::steady_clock::now();
    double elapsedMs = std::chrono::duration<double, std::milli>(now - m_T0).count();
    int frame = static_cast<int>(std::lround(elapsedMs * m_FrameHz / 1000.0));
    if (frame < 0) frame = 0;

    RecordedEvent ev;
    ev.frame = frame;
    ev.padIndex = padIndex;
    ev.state.valid = true;
    ev.state.buttons = buttons;
    ev.state.lt = lt; ev.state.rt = rt;
    ev.state.lsX = lsX; ev.state.lsY = lsY;
    ev.state.rsX = rsX; ev.state.rsY = rsY;
    m_Events.append(ev);
}
