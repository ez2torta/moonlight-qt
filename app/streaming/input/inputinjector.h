#pragma once

#include <QObject>
#include <QString>
#include <QVector>
#include <QMap>

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <mutex>
#include <thread>
#include <vector>

// Frame describing virtual gamepad state at one instant.
// One frame may target one or two pads (pad 0 = P1, pad 1 = P2).
struct InjectorPadState {
    bool present = false;     // if false, this pad is not updated by the frame
    int buttons = 0;          // bitmask of *_FLAG values from Limelight.h
    int lt = 0;               // 0..255
    int rt = 0;               // 0..255
    int lsX = 0, lsY = 0;     // -32768..32767
    int rsX = 0, rsY = 0;
};

struct InjectorEvent {
    std::chrono::steady_clock::time_point deadline;
    InjectorPadState pads[2];
};

// Public-facing sequence representation, frame-indexed.
// Each entry is a delta to apply at the given frame number.
struct InjectorSequence {
    double fps = 120.0;
    int shiftFrames[2] = {0, 0};
    QVector<InjectorEvent> events; // already absolute-deadlined when scheduled
};

class InputInjector : public QObject
{
    Q_OBJECT
public:
    explicit InputInjector(QObject* parent = nullptr);
    ~InputInjector() override;

    // Declares the two virtual controllers to the host. Idempotent.
    // Should be called after the Limelight connection is up.
    void enable();

    // Sends a final neutral state and stops the worker thread.
    void disable();

    bool isEnabled() const { return m_Enabled.load(); }

    // Phase 3: when true, SdlInputHandler::sendGamepadState() and the
    // explicit clear-events in gamepad.cpp will skip LiSendMultiControllerEvent,
    // so physical pads stop reaching the host while the injector is in charge.
    // Read from gamepad.cpp; written by Session when --block-physical-input is set.
    static std::atomic<bool> sBlockPhysical;

public slots:
    // Cancels any active sequence, emits one neutral frame for each pad,
    // then schedules the supplied events. Events use offsets relative
    // to "now"; absolute deadlines are computed inside.
    // shiftFrames[i] is added to frame index of every event targeting pad i.
    void play(double fps,
              const QVector<InjectorEvent>& relativeEvents,
              int shiftPad0,
              int shiftPad1);

    // Cancels and resets to neutral.
    void stopSequence();

    // Sets a static state for a pad until next play()/stopSequence().
    void hold(int padIndex, const InjectorPadState& state);

    // Returns a small status snapshot.
    QString statusJson() const;

private:
    void workerLoop();
    void sendNeutral(int padIndex);
    void sendState(int padIndex, const InjectorPadState& s);
    void declareArrival(int padIndex);

    std::atomic<bool> m_Enabled{false};
    std::atomic<bool> m_Stop{false};
    std::thread m_Worker;
    mutable std::mutex m_Mtx;
    std::condition_variable m_Cv;

    // Pending events sorted by deadline (ascending). Front = next to fire.
    std::vector<InjectorEvent> m_Queue;

    // Last applied state per pad (used for HOLD persistence + neutral diff).
    InjectorPadState m_LastState[2];

    // Active gamepad mask. Bit i set when pad i is virtually present.
    int m_Mask = 0;

    // Stats
    std::atomic<uint64_t> m_EventsApplied{0};
    std::atomic<int64_t> m_LastDriftUs{0};
};
