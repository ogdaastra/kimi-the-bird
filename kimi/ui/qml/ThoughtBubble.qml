import QtQuick

Item {
    id: bubble

    property string text
    property bool thinking: false

    width: Math.min(280, body.implicitWidth + 24)
    height: content.height + 22

    Rectangle {
        id: content
        width: parent.width
        height: body.height + 14
        radius: 12
        color: Qt.rgba(1, 0.99, 0.96, 0.95)
        border.color: "#3d3027"
        border.width: 1.4

        Text {
            id: body
            anchors.centerIn: parent
            width: Math.min(256, implicitWidth)
            text: bubble.thinking ? "· · ·" : bubble.text
            wrapMode: Text.WordWrap
            horizontalAlignment: Text.AlignHCenter
            color: "#3d3027"
            font.pixelSize: 13
            font.italic: !bubble.thinking
            font.bold: bubble.thinking
            elide: Text.ElideRight
            maximumLineCount: 3
        }
    }

    Rectangle {
        x: parent.width / 2 - 2
        y: content.height + 4
        width: 8
        height: 8
        radius: 4
        color: content.color
        border.color: content.border.color
    }
    Rectangle {
        x: parent.width / 2 - 1
        y: content.height + 14
        width: 5
        height: 5
        radius: 2.5
        color: content.color
        border.color: content.border.color
    }
}
