#pragma once

#include <QObject>
#include <QString>
#include <QHash>

class QTcpServer;
class QTcpSocket;
class QJsonObject;
class QJsonArray;
class InputInjector;

class InputControlServer : public QObject
{
    Q_OBJECT
public:
    explicit InputControlServer(InputInjector* injector,
                                quint16 port,
                                const QString& token,
                                QObject* parent = nullptr);
    ~InputControlServer() override;

    bool start();
    void stop();

private slots:
    void onNewConnection();
    void onClientReadyRead();
    void onClientDisconnected();

private:
    void sendJson(QTcpSocket* sock, const QJsonObject& obj);
    void handleMessage(QTcpSocket* sock, const QJsonObject& msg);
    void handlePlay(QTcpSocket* sock, const QJsonObject& msg);
    void handleHold(QTcpSocket* sock, const QJsonObject& msg);
    int  parseButtons(const QJsonArray& arr) const;
    int  parseButtonName(const QString& name) const;

    InputInjector* m_Injector;          // not owned
    QTcpServer*    m_Server = nullptr;
    quint16        m_Port;
    QString        m_Token;

    // Per-socket state: buffered partial line + auth flag.
    struct ClientState {
        QByteArray buffer;
        bool authenticated = false;
    };
    QHash<QTcpSocket*, ClientState> m_Clients;
};
