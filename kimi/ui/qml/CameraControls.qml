import QtQuick

Item {
    id: controls

    required property var rig
    signal interacted
    signal resetRequested

    property point last

    DragHandler {
        id: drag
        target: null
        onActiveChanged: if (active) controls.last = Qt.point(0, 0)
        onTranslationChanged: {
            const dx = translation.x - controls.last.x
            const dy = translation.y - controls.last.y
            controls.last = Qt.point(translation.x, translation.y)
            controls.rig.yaw -= dx * 0.3
            controls.rig.targetPitch = Math.max(6, Math.min(78, controls.rig.targetPitch + dy * 0.2))
            controls.interacted()
        }
    }

    WheelHandler {
        onWheel: event => {
            const factor = 1 - event.angleDelta.y / 1200
            controls.rig.targetDistance = Math.max(110, Math.min(2800, controls.rig.targetDistance * factor))
            controls.interacted()
        }
    }

    TapHandler {
        onDoubleTapped: controls.resetRequested()
    }
}
