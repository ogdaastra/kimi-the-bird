import QtQuick

Rectangle {
    id: button

    property string text
    property bool checked: false
    signal activated

    width: label.implicitWidth + 24
    height: label.implicitHeight + 12
    radius: height / 2
    color: checked ? "#3f6e4e" : (hover.hovered ? "#fffaf0" : "#fbf3df")
    border.color: activeFocus ? "#3a2e24" : "#3f6e4e"
    border.width: activeFocus ? 2 : 1
    activeFocusOnTab: true

    Accessible.role: Accessible.Button
    Accessible.name: text
    Accessible.checkable: true
    Accessible.checked: checked
    Keys.onReturnPressed: button.activated()
    Keys.onSpacePressed: button.activated()

    Text {
        id: label
        anchors.centerIn: parent
        text: button.text
        color: button.checked ? "white" : "#3f6e4e"
        font.pixelSize: 13
        font.bold: true
    }

    HoverHandler {
        id: hover
        cursorShape: Qt.PointingHandCursor
    }

    TapHandler {
        onTapped: button.activated()
    }
}
