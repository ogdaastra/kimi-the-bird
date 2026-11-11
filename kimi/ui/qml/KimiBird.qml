import QtQuick
import QtQuick3D

Node {
    id: bird

    required property var st
    property real clock: 0
    property bool primed: false
    property bool walking: false
    property real heading: 0
    property real wanderX: 0
    property real wanderZ: 0
    property bool hasWanderGoal: false

    readonly property string mode: st.mode
    readonly property bool asleep: st.asleep
    readonly property bool calm: st.reduceMotion
    readonly property real hop: walking && !calm ? Math.abs(Math.sin(clock * 11)) * 6 : 0
    readonly property real sit: asleep ? -5 : (mode === "rest" || mode === "write") && !walking ? -3 : 0
    readonly property bool blinking: asleep || mode === "rest" || (clock % 4.1) < 0.12
    readonly property real headPitch: {
        if (asleep)
            return 28
        if (walking)
            return 0
        if (mode === "eat")
            return Math.max(0, Math.sin(clock * 7)) * 38
        if (mode === "explore")
            return Math.sin(clock * 3) > 0.55 ? 32 : 4
        if (mode === "read" || mode === "research" || mode === "write")
            return 14 + Math.sin(clock * 1.6) * 5
        if (mode === "create")
            return 10 + Math.max(0, Math.sin(clock * 5)) * 18
        return Math.sin(clock * 1.1) * 4
    }
    readonly property real headYaw: !walking && (mode === "observe" || mode === "idle") && !calm ? Math.sin(clock * 0.7) * 38 : 0
    readonly property real flap: {
        if (calm)
            return 0
        if (mode === "create" && !walking)
            return Math.sin(clock * 14) * 22
        if (walking)
            return Math.max(0, Math.sin(clock * 11)) * 14
        return 0
    }
    readonly property real tailAngle: -40 + Math.sin(clock * 5) * (walking ? 10 : 3)

    function shortestAngle(from, to) {
        return ((to - from) % 360 + 540) % 360 - 180
    }

    function advance(dt) {
        let tx = st.kimiX
        let tz = st.kimiZ
        if (st.wander && hasWanderGoal) {
            tx = wanderX
            tz = wanderZ
        }
        if (!primed) {
            x = tx
            z = tz
            primed = true
            if (st.kimiHeading > -900)
                heading = st.kimiHeading
            return
        }
        const dx = tx - x
        const dz = tz - z
        const d = Math.hypot(dx, dz)
        if (d > 1200) {
            x = tx
            z = tz
            walking = false
        } else if (d > 1.5) {
            const speed = st.moving ? Math.max(45, d * 2.2) : Math.max(35, Math.min(90, d * 1.5))
            const stepLen = Math.min(d, speed * dt)
            x += dx / d * stepLen
            z += dz / d * stepLen
            walking = true
            heading += shortestAngle(heading, Math.atan2(dx, dz) * 180 / Math.PI) * Math.min(1, dt * 8)
        } else {
            walking = false
            if (st.kimiHeading > -900)
                heading += shortestAngle(heading, st.kimiHeading) * Math.min(1, dt * 3)
        }
    }

    eulerRotation.y: heading
    scale: Qt.vector3d(1.2, 1.2, 1.2)

    Timer {
        running: bird.st.wander && !bird.asleep
        repeat: true
        triggeredOnStart: true
        interval: 3000
        onTriggered: {
            const a = Math.random() * Math.PI * 2
            const r = Math.random() * bird.st.wanderRadius
            bird.wanderX = bird.st.kimiX + Math.cos(a) * r
            bird.wanderZ = bird.st.kimiZ + Math.sin(a) * r
            bird.hasWanderGoal = true
            interval = 2600 + Math.random() * 3400
        }
        onRunningChanged: if (!running) bird.hasWanderGoal = false
    }

    PrincipledMaterial {
        id: feathers
        baseColor: "#7d95b8"
        roughness: 0.8
    }
    PrincipledMaterial {
        id: wingFeathers
        baseColor: "#5f7799"
        roughness: 0.8
    }
    PrincipledMaterial {
        id: chestFeathers
        baseColor: "#f6c6a3"
        roughness: 0.85
    }
    PrincipledMaterial {
        id: legColour
        baseColor: "#c98a4b"
        roughness: 0.7
    }
    PrincipledMaterial {
        id: eyeColour
        baseColor: "#211b18"
        roughness: 0.15
    }

    Model {
        source: "#Cylinder"
        position: Qt.vector3d(-5, 4 + bird.sit / 2, 1)
        scale: Qt.vector3d(0.018, 0.08 + bird.sit / 100, 0.018)
        materials: legColour
    }
    Model {
        source: "#Cylinder"
        position: Qt.vector3d(5, 4 + bird.sit / 2, 1)
        scale: Qt.vector3d(0.018, 0.08 + bird.sit / 100, 0.018)
        materials: legColour
    }

    Node {
        y: 8 + bird.hop + bird.sit
        scale: Qt.vector3d(1, 1 + Math.sin(bird.clock * 2.4) * (bird.calm ? 0 : 0.015), 1)

        Model {
            source: "#Sphere"
            y: 14
            scale: Qt.vector3d(0.34, 0.31, 0.37)
            materials: feathers
        }
        Model {
            source: "#Sphere"
            position: Qt.vector3d(0, 11, 9)
            scale: Qt.vector3d(0.25, 0.22, 0.18)
            materials: chestFeathers
        }
        Node {
            position: Qt.vector3d(-15, 18, -1)
            eulerRotation.z: -bird.flap
            Model {
                source: "#Sphere"
                y: -4
                scale: Qt.vector3d(0.06, 0.15, 0.22)
                materials: wingFeathers
            }
        }
        Node {
            position: Qt.vector3d(15, 18, -1)
            eulerRotation.z: bird.flap
            Model {
                source: "#Sphere"
                y: -4
                scale: Qt.vector3d(0.06, 0.15, 0.22)
                materials: wingFeathers
            }
        }
        Node {
            position: Qt.vector3d(0, 19, -14)
            eulerRotation.x: bird.tailAngle
            Model {
                source: "#Cube"
                z: -8
                scale: Qt.vector3d(0.08, 0.022, 0.17)
                materials: wingFeathers
            }
        }
        Node {
            position: Qt.vector3d(0, 25, 8)
            eulerRotation.x: bird.headPitch
            eulerRotation.y: bird.headYaw

            Model {
                source: "#Sphere"
                position: Qt.vector3d(0, 4, 2)
                scale: Qt.vector3d(0.22, 0.21, 0.22)
                materials: feathers
            }
            Model {
                source: "#Sphere"
                position: Qt.vector3d(-5.6, 6, 10.4)
                scale: Qt.vector3d(0.045, bird.blinking ? 0.006 : 0.045, 0.045)
                materials: eyeColour
            }
            Model {
                source: "#Sphere"
                position: Qt.vector3d(5.6, 6, 10.4)
                scale: Qt.vector3d(0.045, bird.blinking ? 0.006 : 0.045, 0.045)
                materials: eyeColour
            }
            Model {
                source: "#Cube"
                position: Qt.vector3d(-6.2, 9.6, 9)
                eulerRotation.z: -12
                scale: Qt.vector3d(0.065, 0.012, 0.03)
                materials: PrincipledMaterial {
                    baseColor: "#f2eadf"
                    roughness: 0.9
                }
            }
            Model {
                source: "#Cube"
                position: Qt.vector3d(6.2, 9.6, 9)
                eulerRotation.z: 12
                scale: Qt.vector3d(0.065, 0.012, 0.03)
                materials: PrincipledMaterial {
                    baseColor: "#f2eadf"
                    roughness: 0.9
                }
            }
            Model {
                source: "#Cone"
                position: Qt.vector3d(0, 3, 13)
                eulerRotation.x: 90
                scale: Qt.vector3d(0.035, 0.08, 0.035)
                materials: PrincipledMaterial {
                    baseColor: "#f0a347"
                    roughness: 0.5
                }
            }
        }
    }
}
