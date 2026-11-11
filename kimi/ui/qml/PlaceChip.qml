import QtQuick

Rectangle {
    id: chip

    required property var place
    property bool current: false
    property bool shown: false
    signal activated

    visible: shown
    width: label.implicitWidth + 20
    height: label.implicitHeight + 8
    radius: 6
    color: current ? "#eef5e6" : (mouse.hovered || activeFocus ? "#fffaf0" : "#fbf3df")
    border.color: current ? "#3f6e4e" : (activeFocus ? "#3f6e4e" : "#8a6f4f")
    border.width: current || activeFocus ? 2 : 1
    activeFocusOnTab: true

    Accessible.role: Accessible.Button
    Accessible.name: qsTr("Look at %1").arg(place.name)
    Keys.onReturnPressed: chip.activated()
    Keys.onSpacePressed: chip.activated()

    Text {
        id: label
        anchors.centerIn: parent
        text: chip.place.name
        color: "#3a2e24"
        font.family: "Georgia"
        font.pixelSize: 13
        font.bold: true
    }

    HoverHandler {
        id: mouse
        cursorShape: Qt.PointingHandCursor
    }

    TapHandler {
        onTapped: chip.activated()
    }
}
