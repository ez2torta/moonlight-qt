#pragma once

#include <QObject>
#include <QString>
#include <QVector>

#include <atomic>
#include <chrono>
#include <mutex>

// Captures the per-pad state stream produced by SdlInputHandler::sendGamepadState()
// and writes it as a JSON sequence file using the same schema the InputInjector /
// inputbench play.py replayer consume (events mode with absolute pad state).
//
// Lifecycle:
//   - Session creates one instance when --input-record FILE is supplied.
//   - SdlInputHandler::sendGamepadState() calls InputRecorder::tap(...) right
//     before LiSendMultiControllerEvent, so we capture exactly what the host
//     received (post mouse-emulation, post single-controller merge).
//   - On Session teardown, finish() flushes the file. If the process is killed
//     before that runs, no file is produced — by design, recording is a "save
//     on clean exit" operation. Use STOP from inputbench (future) for live save.
//
// Format (matches play.py "events" mode):
//   {
//     "frame_hz": 60.0,
//     "shift_pad0": 0,
//     "shift_pad1": 0,
//     "events": [
//       { "frame": 0,  "pads": { "0": { "buttons": [...], "lt": 0, ... } } },
//       { "frame": 12, "pads": { "0": { "buttons": ["A"], ... } } },
//       ...
//     ]
//   }
//
// We emit ONE event per state change per pad. Frame number = round(elapsed_ms * hz / 1000).
// Buttons are written as the names InputControlServer accepts so the output is
// directly replayable.
class InputRecorder : public QObject
{
    Q_OBJECT
public:
    explicit InputRecorder(const QString& outputPath, double frameHz = 60.0,
                           QObject* parent = nullptr);
    ~InputRecorder() override;

    // Begin capture window. tap() before start() is silently dropped.
    void start();

    // Stop capture and write the JSON file. Safe to call multiple times.
    void finish();

    bool isActive() const { return m_Active.load(); }

    // Hot-path tap. Called from SdlInputHandler::sendGamepadState() right before
    // LiSendMultiControllerEvent. Lock-light: builds an event only when the
    // per-pad state actually changed since the last tap for that pad.
    static void tap(int padIndex, int buttons,
                    int lt, int rt,
                    int lsX, int lsY, int rsX, int rsY);

private:
    struct PadSnapshot {
        bool valid = false;
        int buttons = 0;
        int lt = 0, rt = 0;
        int lsX = 0, lsY = 0, rsX = 0, rsY = 0;
    };

    struct RecordedEvent {
        int frame;            // absolute frame index from start
        int padIndex;         // 0..15 (we expect 0/1)
        PadSnapshot state;    // post-change absolute state
    };

    void recordInstance(int padIndex, int buttons,
                        int lt, int rt,
                        int lsX, int lsY, int rsX, int rsY);

    static InputRecorder* s_Instance; // single global recorder, or nullptr.

    QString m_OutputPath;
    double m_FrameHz;

    std::atomic<bool> m_Active{false};
    std::chrono::steady_clock::time_point m_T0;

    mutable std::mutex m_Mtx;
    QVector<RecordedEvent> m_Events;
    PadSnapshot m_LastPad[16];
};
