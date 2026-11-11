import QtQuick

Item {
    id: overlay

    required property var view
    required property var kimi
    required property var st
    required property var lay
    property string cameraMode: "follow"
    property vector3d lookAt: Qt.vector3d(0, 0, 0)
    property int shownSerial: 0
    property bool bubbleOn: false

    signal followRequested
    signal townRequested
    signal placeRequested(var place)
    signal curiosityRequested(var curio)

    function reposition() {
        for (let i = 0; i < labels.count; ++i) {
            const chip = labels.itemAt(i)
            if (!chip)
                continue
            const p = view.mapFrom3DScene(Qt.vector3d(chip.place.x, chip.place.y, chip.place.z))
            chip.shown = p.z > 0 && p.x > -60 && p.x < width + 60 && p.y > -20 && p.y < height + 20
            chip.x = p.x - chip.width / 2
            chip.y = p.y - chip.height
        }
        const seen = st.curiositiesSeen || []
        for (let j = 0; j < curioLabels.count; ++j) {
            const cc = curioLabels.itemAt(j)
            if (!cc)
                continue
            const c = cc.curio
            const near = Math.hypot(c.x - lookAt.x, c.z - lookAt.z) < 340
            const cp = view.mapFrom3DScene(Qt.vector3d(c.x, c.y, c.z))
            cc.current = st.curiosity === c.id
            cc.seen = seen.indexOf(c.id) >= 0
            cc.shown = cameraMode !== "town" && (near || cc.current) && cp.z > 0
                       && cp.x > -40 && cp.x < width + 40 && cp.y > -10 && cp.y < height + 10
            cc.x = cp.x - cc.width / 2
            cc.y = cp.y - cc.height
        }
        const head = view.mapFrom3DScene(Qt.vector3d(kimi.x, kimi.y + 30, kimi.z))
        kimiAnchor.x = head.x
        kimiAnchor.y = head.y
        kimiAnchor.visible = head.z > 0
    }

    onStChanged: {
        if (st.thoughtSerial !== shownSerial) {
            shownSerial = st.thoughtSerial
            if (st.thought.length > 0) {
                bubbleOn = true
                bubbleTimer.restart()
            }
        }
    }

    Timer {
        id: bubbleTimer
        interval: 9000
        onTriggered: overlay.bubbleOn = false
    }

    Repeater {
        id: curioLabels
        model: overlay.lay.curiosities
        delegate: CuriosityChip {
            required property var modelData
            curio: modelData
            onActivated: overlay.curiosityRequested(modelData)
        }
    }

    Repeater {
        id: labels
        model: overlay.lay.places
        delegate: PlaceChip {
            required property var modelData
            place: modelData
            current: overlay.st.location === modelData.id && !overlay.st.moving
            onActivated: overlay.placeRequested(modelData)
        }
    }

    Item {
        id: kimiAnchor

        ThoughtBubble {
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.top
            anchors.bottomMargin: 4
            text: overlay.st.thinking ? "" : overlay.st.thought
            thinking: overlay.st.thinking
            visible: overlay.st.thinking || overlay.bubbleOn
        }

        Text {
            visible: overlay.st.asleep
            anchors.left: parent.right
            anchors.bottom: parent.top
            text: qsTr("z z Z")
            color: "#f4ecd8"
            style: Text.Outline
            styleColor: "#3a2e24"
            font.family: "Georgia"
            font.pixelSize: 18
            font.italic: true
        }

        Rectangle {
            visible: overlay.cameraMode === "town" && !overlay.st.thinking && !overlay.bubbleOn
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.top
            width: tag.implicitWidth + 14
            height: tag.implicitHeight + 6
            radius: height / 2
            color: "#3f6e4e"
            Text {
                id: tag
                anchors.centerIn: parent
                text: qsTr("Kimi")
                color: "white"
                font.pixelSize: 12
                font.bold: true
            }
        }
    }

    Row {
        anchors.top: parent.top
        anchors.right: parent.right
        anchors.margins: 12
        spacing: 8

        ChipButton {
            text: qsTr("Follow Kimi")
            checked: overlay.cameraMode === "follow"
            onActivated: overlay.followRequested()
        }
        ChipButton {
            text: qsTr("Whole town")
            checked: overlay.cameraMode === "town"
            onActivated: overlay.townRequested()
        }
    }

    Rectangle {
        anchors.left: parent.left
        anchors.bottom: parent.bottom
        anchors.margins: 12
        width: hint.implicitWidth + 18
        height: hint.implicitHeight + 10
        radius: 8
        color: Qt.rgba(0.98, 0.95, 0.88, 0.85)
        border.color: "#8a6f4f"
        Text {
            id: hint
            anchors.centerIn: parent
            text: qsTr("Drag to look around · scroll to zoom · click a place or curiosity to look · double-click to follow Kimi")
            color: "#3a2e24"
            font.pixelSize: 12
        }
    }
}
