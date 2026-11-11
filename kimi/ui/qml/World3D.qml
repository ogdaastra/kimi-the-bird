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
        rig.targetDistance = 270
        rig.targetPitch = 32
    }

    function focusCuriosity(c) {
        focusPoint = Qt.vector3d(c.x, c.y * 0.5, c.z)
        cameraMode = "place"
        rig.targetDistance = 260
        rig.targetPitch = 30
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
        rig.blockedDistance = hit.objectHit && hit.distance < rig.targetDistance ? Math.max(70, hit.distance - 25) : 1e9
    }

    function step(dt) {
        clock += dt
        kimi.advance(dt)
        let goal
        if (cameraMode === "follow")
            goal = Qt.vector3d(kimi.x, kimi.y + 14, kimi.z)
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
            groundAt: (gx, gz) => root.bridge.groundHeight(gx, gz)
        }

        Repeater3D {
            model: root.lay.beacons
            delegate: Model {
                required property var modelData
                source: "#Sphere"
                position: Qt.vector3d(modelData.x, modelData.y, modelData.z)
                scale: Qt.vector3d(0.13, 0.13, 0.13)
                // long, short, short, long - the lighthouse's undeciphered message
                readonly property real phase: (root.clock % 6.0)
                readonly property bool lit: (phase < 1.2) || (phase > 1.6 && phase < 1.9) || (phase > 2.3 && phase < 2.6) || (phase > 3.0 && phase < 4.2)
                visible: root.st.night > 0.25 && (lit || root.st.reduceMotion)
                castsShadows: false
                materials: PrincipledMaterial {
                    baseColor: "#fff2c0"
                    emissiveFactor: Qt.vector3d(1.0, 0.85, 0.45).times(2.5)
                    lighting: PrincipledMaterial.NoLighting
                }
            }
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
        lookAt: root.cameraMode === "follow" ? Qt.vector3d(kimi.x, 0, kimi.z) : root.focusPoint
        onFollowRequested: root.followKimi()
        onTownRequested: root.showTown()
        onPlaceRequested: place => root.focusPlace(place)
        onCuriosityRequested: c => root.focusCuriosity(c)
    }

    FrameAnimation {
        running: root.visible
        onTriggered: root.step(Math.min(frameTime, 0.1))
    }
}
