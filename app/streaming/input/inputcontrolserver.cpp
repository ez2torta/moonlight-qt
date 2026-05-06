#include "inputcontrolserver.h"
#include "inputinjector.h"

#include <Limelight.h>
#include <SDL.h>

#include <QHostAddress>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QTcpServer>
#include <QTcpSocket>

#include <chrono>
#include <functional>

InputControlServer::InputControlServer(InputInjector* injector,
                                       quint16 port,
                                       const QString& token,
                                       QObject* parent)
    : QObject(parent),
      m_Injector(injector),
      m_Port(port),
      m_Token(token)
{
}

InputControlServer::~InputControlServer()
{
    stop();
}

bool InputControlServer::start()
{
    if (m_Server) return true;

    m_Server = new QTcpServer(this);
    connect(m_Server, &QTcpServer::newConnection,
            this, &InputControlServer::onNewConnection);

    // Loopback only — no external exposure.
    if (!m_Server->listen(QHostAddress::LocalHost, m_Port)) {
        SDL_LogError(SDL_LOG_CATEGORY_APPLICATION,
                     "InputControlServer: listen failed on 127.0.0.1:%u: %s",
                     m_Port,
                     qPrintable(m_Server->errorString()));
        delete m_Server;
        m_Server = nullptr;
        return false;
    }
    SDL_LogInfo(SDL_LOG_CATEGORY_APPLICATION,
                "InputControlServer: listening on 127.0.0.1:%u",
                m_Server->serverPort());
    return true;
}

void InputControlServer::stop()
{
    if (!m_Server) return;
    for (auto it = m_Clients.begin(); it != m_Clients.end(); ++it) {
        it.key()->disconnectFromHost();
        it.key()->deleteLater();
    }
    m_Clients.clear();
    m_Server->close();
    m_Server->deleteLater();
    m_Server = nullptr;
}

void InputControlServer::onNewConnection()
{
    while (m_Server && m_Server->hasPendingConnections()) {
        QTcpSocket* sock = m_Server->nextPendingConnection();
        if (!sock) continue;

        // Defense in depth: even though we only listen on loopback, check.
        if (sock->peerAddress() != QHostAddress::LocalHost
            && sock->peerAddress() != QHostAddress(QHostAddress::LocalHostIPv6)) {
            sock->disconnectFromHost();
            sock->deleteLater();
            continue;
        }

        m_Clients.insert(sock, ClientState{});
        connect(sock, &QTcpSocket::readyRead,
                this, &InputControlServer::onClientReadyRead);
        connect(sock, &QTcpSocket::disconnected,
                this, &InputControlServer::onClientDisconnected);
    }
}

void InputControlServer::onClientDisconnected()
{
    auto* sock = qobject_cast<QTcpSocket*>(sender());
    if (!sock) return;
    m_Clients.remove(sock);
    sock->deleteLater();
}

void InputControlServer::onClientReadyRead()
{
    auto* sock = qobject_cast<QTcpSocket*>(sender());
    if (!sock) return;
    auto it = m_Clients.find(sock);
    if (it == m_Clients.end()) return;

    it->buffer.append(sock->readAll());
    // Hard cap to prevent memory abuse.
    if (it->buffer.size() > (1 << 22)) {
        sock->disconnectFromHost();
        return;
    }

    int nl;
    while ((nl = it->buffer.indexOf('\n')) >= 0) {
        QByteArray line = it->buffer.left(nl);
        it->buffer.remove(0, nl + 1);
        if (line.endsWith('\r')) line.chop(1);
        if (line.isEmpty()) continue;

        QJsonParseError err{};
        auto doc = QJsonDocument::fromJson(line, &err);
        if (err.error != QJsonParseError::NoError || !doc.isObject()) {
            QJsonObject e;
            e["op"] = "ERR";
            e["msg"] = "BAD_JSON";
            sendJson(sock, e);
            continue;
        }
        handleMessage(sock, doc.object());
    }
}

void InputControlServer::sendJson(QTcpSocket* sock, const QJsonObject& obj)
{
    if (!sock) return;
    auto data = QJsonDocument(obj).toJson(QJsonDocument::Compact);
    data.append('\n');
    sock->write(data);
}

void InputControlServer::handleMessage(QTcpSocket* sock, const QJsonObject& msg)
{
    auto it = m_Clients.find(sock);
    if (it == m_Clients.end()) return;

    const QString op = msg.value("op").toString();

    if (!it->authenticated) {
        if (op != "HELLO") {
            QJsonObject e;
            e["op"] = "ERR"; e["msg"] = "EXPECTED_HELLO";
            sendJson(sock, e);
            sock->disconnectFromHost();
            return;
        }
        const QString token = msg.value("token").toString();
        if (token.isEmpty() || token != m_Token) {
            QJsonObject e;
            e["op"] = "ERR"; e["msg"] = "BAD_TOKEN";
            sendJson(sock, e);
            sock->disconnectFromHost();
            return;
        }
        it->authenticated = true;

        QJsonObject ok;
        ok["op"] = "OK";
        QJsonArray ctrls; ctrls.append(0); ctrls.append(1);
        ok["controllers"] = ctrls;
        sendJson(sock, ok);
        return;
    }

    if (op == "PLAY") {
        handlePlay(sock, msg);
    } else if (op == "STOP") {
        m_Injector->stopSequence();
        QJsonObject ok; ok["op"] = "OK"; sendJson(sock, ok);
    } else if (op == "HOLD") {
        handleHold(sock, msg);
    } else if (op == "STATUS") {
        QJsonObject st;
        st["op"] = "STATUS";
        st["data"] = QJsonDocument::fromJson(m_Injector->statusJson().toUtf8()).object();
        sendJson(sock, st);
    } else if (op == "PING") {
        QJsonObject ok; ok["op"] = "PONG"; sendJson(sock, ok);
    } else {
        QJsonObject e;
        e["op"] = "ERR"; e["msg"] = "UNKNOWN_OP";
        sendJson(sock, e);
    }
}

int InputControlServer::parseButtonName(const QString& name) const
{
    static const QHash<QString, int> map = {
        {"A", A_FLAG}, {"B", B_FLAG}, {"X", X_FLAG}, {"Y", Y_FLAG},
        {"UP", UP_FLAG}, {"DOWN", DOWN_FLAG},
        {"LEFT", LEFT_FLAG}, {"RIGHT", RIGHT_FLAG},
        {"LB", LB_FLAG}, {"RB", RB_FLAG},
        {"LS", LS_CLK_FLAG}, {"RS", RS_CLK_FLAG},
        {"BACK", BACK_FLAG}, {"START", PLAY_FLAG},
        {"GUIDE", SPECIAL_FLAG},
        {"MISC", MISC_FLAG},
        {"PADDLE1", PADDLE1_FLAG}, {"PADDLE2", PADDLE2_FLAG},
        {"PADDLE3", PADDLE3_FLAG}, {"PADDLE4", PADDLE4_FLAG},
        {"TOUCHPAD", TOUCHPAD_FLAG},
    };
    return map.value(name.toUpper(), 0);
}

int InputControlServer::parseButtons(const QJsonArray& arr) const
{
    int flags = 0;
    for (const auto& v : arr) {
        flags |= parseButtonName(v.toString());
    }
    return flags;
}

static InjectorPadState parsePadObject(const QJsonObject& obj,
                                       std::function<int(const QJsonArray&)> btnParse)
{
    InjectorPadState s;
    s.present = true;
    if (obj.contains("b") && obj.value("b").isArray()) {
        s.buttons = btnParse(obj.value("b").toArray());
    } else if (obj.contains("buttons") && obj.value("buttons").isArray()) {
        s.buttons = btnParse(obj.value("buttons").toArray());
    }
    s.lt = obj.value("lt").toInt(0);
    s.rt = obj.value("rt").toInt(0);
    s.lsX = obj.value("lx").toInt(0);
    s.lsY = obj.value("ly").toInt(0);
    s.rsX = obj.value("rx").toInt(0);
    s.rsY = obj.value("ry").toInt(0);
    return s;
}

void InputControlServer::handleHold(QTcpSocket* sock, const QJsonObject& msg)
{
    int pad = msg.value("pad").toInt(0);
    if (pad < 0 || pad > 1) {
        QJsonObject e; e["op"] = "ERR"; e["msg"] = "BAD_PAD"; sendJson(sock, e);
        return;
    }
    auto state = parsePadObject(msg, [this](const QJsonArray& a){ return parseButtons(a); });
    m_Injector->hold(pad, state);
    QJsonObject ok; ok["op"] = "OK"; sendJson(sock, ok);
}

void InputControlServer::handlePlay(QTcpSocket* sock, const QJsonObject& msg)
{
    double fps = msg.value("fps").toDouble(120.0);
    if (fps <= 0.0) fps = 120.0;

    int shift0 = 0, shift1 = 0;
    if (msg.contains("shift_frames") && msg.value("shift_frames").isObject()) {
        auto sf = msg.value("shift_frames").toObject();
        shift0 = sf.value("0").toInt(0);
        shift1 = sf.value("1").toInt(0);
    }

    QVector<InjectorEvent> events;
    auto seq = msg.value("seq").toObject();
    const QString mode = seq.value("mode").toString("events");
    const auto frameUs = static_cast<int64_t>(1e6 / fps);
    auto btnParse = [this](const QJsonArray& a){ return parseButtons(a); };

    if (mode == "dense") {
        // Each entry is an absolute pad state for that frame index.
        // Diff against running state per pad and emit when changed.
        InjectorPadState running[2];
        bool init[2] = {false, false};
        const auto frames = seq.value("frames").toArray();
        for (int f = 0; f < frames.size(); ++f) {
            const auto frameObj = frames.at(f).toObject();
            for (int pad = 0; pad < 2; ++pad) {
                const QString key = QString::number(pad);
                if (!frameObj.contains(key)) continue;
                auto state = parsePadObject(frameObj.value(key).toObject(), btnParse);
                if (init[pad]
                    && state.buttons == running[pad].buttons
                    && state.lt == running[pad].lt && state.rt == running[pad].rt
                    && state.lsX == running[pad].lsX && state.lsY == running[pad].lsY
                    && state.rsX == running[pad].rsX && state.rsY == running[pad].rsY) {
                    continue; // unchanged, skip emit
                }
                running[pad] = state;
                init[pad] = true;

                InjectorEvent ev;
                // Encode the relative offset in deadline.time_since_epoch().
                ev.deadline = std::chrono::steady_clock::time_point(
                    std::chrono::microseconds(static_cast<int64_t>(f) * frameUs));
                ev.pads[pad] = state;
                events.push_back(ev);
            }
        }
    } else {
        // Event mode: list of {t, pad, down[], up[], lt, rt, lx,ly, rx,ry}
        InjectorPadState running[2]; // accumulated per pad
        running[0].present = true;
        running[1].present = true;
        const auto evs = seq.value("events").toArray();
        for (const auto& ev : evs) {
            const auto o = ev.toObject();
            int t = o.value("t").toInt(0);
            int pad = o.value("pad").toInt(0);
            if (pad < 0 || pad > 1) continue;

            if (o.contains("down")) {
                running[pad].buttons |= parseButtons(o.value("down").toArray());
            }
            if (o.contains("up")) {
                running[pad].buttons &= ~parseButtons(o.value("up").toArray());
            }
            if (o.contains("lt")) running[pad].lt = o.value("lt").toInt(0);
            if (o.contains("rt")) running[pad].rt = o.value("rt").toInt(0);
            if (o.contains("lx")) running[pad].lsX = o.value("lx").toInt(0);
            if (o.contains("ly")) running[pad].lsY = o.value("ly").toInt(0);
            if (o.contains("rx")) running[pad].rsX = o.value("rx").toInt(0);
            if (o.contains("ry")) running[pad].rsY = o.value("ry").toInt(0);

            InjectorEvent out;
            out.deadline = std::chrono::steady_clock::time_point(
                std::chrono::microseconds(static_cast<int64_t>(t) * frameUs));
            out.pads[pad] = running[pad];
            events.push_back(out);
        }
    }

    m_Injector->play(fps, events, shift0, shift1);

    QJsonObject ok;
    ok["op"] = "OK";
    ok["scheduled"] = events.size();
    sendJson(sock, ok);
}
