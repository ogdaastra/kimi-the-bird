import QtQuick
import QtQuick3D
import Kimi3D

Item {
    id: root

    required property var bridge
    readonly property var st: bridge.state
    readonly property var lay: bridge.layout
    readonly property bool highQuality: st.quality === "high"
    property string cameraMode: "follow"
    property vector3d focusPoint: Qt.vector3d(0, 0, 0)
    property real clock: 0
    property real lastInteraction: -100

    function critter(kind) {
        for (let i = 0; i < lay.critters.length; ++i)
            if (lay.critters[i].kind === kind)
                return lay.critters[i]
        return lay.critters[0]
    }

    function focusPlace(place) {
        focusPoint = Qt.vector3d(place.x, 40, place.z)
        cameraMode = "place"
        rig.targetDistance = 640
    }

    function followKimi() {
        cameraMode = "follow"
        rig.targetDistance = 500
        rig.targetPitch = 38
    }

    function showTown() {
        cameraMode = "town"
        rig.targetDistance = 2300
        rig.targetPitch = 40
    }

    function keepCameraClear() {
        if (cameraMode === "town") {
            rig.blockedDistance = 1e9
            return
        }
        const origin = rig.position
        const toCamera = rig.camera.scenePosition.minus(origin)
        if (toCamera.length() < 1)
            return
        const hit = view.rayPick(origin, toCamera.normalized())
        rig.blockedDistance = hit.objectHit && hit.distance < rig.targetDistance ? Math.max(90, hit.distance - 30) : 1e9
    }

    function step(dt) {
        clock += dt
        kimi.advance(dt)
        let goal
        if (cameraMode === "follow")
            goal = Qt.vector3d(kimi.x, 28, kimi.z)
        else if (cameraMode === "place")
            goal = focusPoint
        else
            goal = Qt.vector3d(0, 0, 0)
        const idle = clock - lastInteraction > 6
        if (cameraMode === "town" && idle && !st.reduceMotion)
            rig.yaw += dt * 3
        if (cameraMode === "follow" && clock - lastInteraction > 8)
            rig.yaw += kimi.shortestAngle(rig.yaw, st.viewYaw) * Math.min(1, dt * (st.moving ? 0.6 : 1.0))
        rig.follow(goal, dt)
        keepCameraClear()
        overlay.reposition()
    }

    View3D {
        id: view
        anchors.fill: parent
        camera: rig.camera
        environment: SceneEnvironment {
            backgroundMode: SceneEnvironment.Color
            clearColor: root.st.skyHorizon
            antialiasingMode: root.highQuality ? SceneEnvironment.MSAA : SceneEnvironment.NoAA
            antialiasingQuality: SceneEnvironment.High
            fog: Fog {
                enabled: root.st.fog
                color: root.st.fogColor
                density: 0.9
                depthEnabled: true
                depthNear: 200
                depthFar: 2000
            }
        }

        CameraRig {
            id: rig
        }

        SkyAndLight {
            st: root.st
            highQuality: root.highQuality
            center: rig.position
        }

        TownScene {
            st: root.st
        }

        TownLife {
            st: root.st
            lay: root.lay
            clock: root.clock
        }

        Hedgehog {
            readonly property var spot: root.critter("hedgehog")
            position: Qt.vector3d(spot.x, 0, spot.z)
            eulerRotation.y: spot.facing
            visible: root.st.night < 0.6
            clock: root.clock
        }

        Owl {
            readonly property var spot: root.critter("owl")
            position: Qt.vector3d(spot.x, 0, spot.z)
            eulerRotation.y: spot.facing
            visible: root.st.night < 0.6
            clock: root.clock
        }

        Cat {
            readonly property var spot: root.critter("cat")
            position: Qt.vector3d(spot.x, 0, spot.z)
            eulerRotation.y: spot.facing
            visible: root.st.night < 0.6
            clock: root.clock
        }

        KimiBird {
            id: kimi
            st: root.st
            clock: root.clock
        }

        Weather {
            st: root.st
            highQuality: root.highQuality
            center: rig.position
            clock: root.clock
        }
    }

    CameraControls {
        anchors.fill: parent
        rig: rig
        onInteracted: root.lastInteraction = root.clock
        onResetRequested: root.followKimi()
    }

    Overlay {
        id: overlay
        anchors.fill: parent
        view: view
        kimi: kimi
        st: root.st
        lay: root.lay
        cameraMode: root.cameraMode
        onFollowRequested: root.followKimi()
        onTownRequested: root.showTown()
        onPlaceRequested: place => root.focusPlace(place)
    }

    FrameAnimation {
        running: root.visible
        onTriggered: root.step(Math.min(frameTime, 0.1))
    }
}
