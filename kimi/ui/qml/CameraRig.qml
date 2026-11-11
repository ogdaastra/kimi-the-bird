import QtQuick
import QtQuick3D

Node {
    id: rig

    property alias camera: cam
    property real yaw: 30
    property real pitch: 38
    property real targetPitch: 38
    property real distance: 500
    property real targetDistance: 500
    property real blockedDistance: 1e9
    property bool primed: false

    function follow(goal, dt) {
        if (!primed) {
            position = goal
            primed = true
            return
        }
        const k = Math.min(1, dt * 2.5)
        position = Qt.vector3d(position.x + (goal.x - position.x) * k,
                               position.y + (goal.y - position.y) * k,
                               position.z + (goal.z - position.z) * k)
        const wanted = Math.min(targetDistance, blockedDistance)
        distance += (wanted - distance) * Math.min(1, dt * (wanted < distance ? 6 : 2))
        pitch += (targetPitch - pitch) * Math.min(1, dt * 3)
    }

    eulerRotation.y: yaw

    Node {
        eulerRotation.x: -rig.pitch

        PerspectiveCamera {
            id: cam
            z: rig.distance
            clipNear: 4
            clipFar: 24000
            fieldOfView: 40
        }
    }
}
