import QtQuick

Rectangle {
    id: chip

    required property var curio
    property bool seen: false
    property bool current: false
    property bool shown: false
    signal activated

    visible: shown
    width: row.implicitWidth + 14
    height: row.implicitHeight + 6
    radius: height / 2
    color: current ? "#fff4cf" : (mouse.hovered || activeFocus ? "#fffaf0" : Qt.rgba(0.99, 0.96, 0.89, 0.88))
    border.color: current ? "#b8860b" : "#a08a6a"
    border.width: current || activeFocus ? 2 : 1
    activeFocusOnTab: true

    Accessible.role: Accessible.Button
    Accessible.name: qsTr("Look at %1").arg(curio.name)
    Keys.onReturnPressed: chip.activated()
    Keys.onSpacePressed: chip.activated()

    Row {
        id: row
        anchors.centerIn: parent
        spacing: 5

        Rectangle {
            anchors.verticalCenter: parent.verticalCenter
            width: 8
            height: 8
            rotation: 45
            color: chip.seen ? "#e8b73a" : "#fbf3df"
            border.color: "#6b4a33"
            border.width: 1
        }
        Text {
            text: chip.curio.name
            color: "#3a2e24"
            font.family: "Georgia"
            font.pixelSize: 11
            font.italic: !chip.seen
        }
    }

    HoverHandler {
        id: mouse
        cursorShape: Qt.PointingHandCursor
    }

    TapHandler {
        onTapped: chip.activated()
    }
}
