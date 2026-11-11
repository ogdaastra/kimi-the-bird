import QtQuick
import QtQuick3D

Node {
    id: hedgehog

    property real clock: 0

    eulerRotation.z: Math.sin(clock * 1.3) * 2

    PrincipledMaterial {
        id: fur
        baseColor: "#8a6a50"
        roughness: 0.9
    }
    PrincipledMaterial {
        id: spikes
        baseColor: "#5d4636"
        roughness: 0.9
    }

    Model {
        source: "#Sphere"
        y: 22
        scale: Qt.vector3d(0.36, 0.34, 0.42)
        materials: fur
    }
    Repeater3D {
        model: 22
        delegate: Model {
            required property int index
            readonly property real a: index * 2.4
            readonly property real e: 0.35 + (index % 5) * 0.22
            source: "#Cone"
            position: Qt.vector3d(Math.cos(a) * 16 * Math.cos(e), 22 + 16 * Math.sin(e), -4 + Math.sin(a) * 18 * Math.cos(e) - 4)
            eulerRotation: Qt.vector3d(-60 * Math.cos(a), 0, 60 * Math.sin(a) - 0)
            scale: Qt.vector3d(0.05, 0.12, 0.05)
            materials: spikes
        }
    }
    Model {
        source: "#Sphere"
        position: Qt.vector3d(0, 22, 18)
        scale: Qt.vector3d(0.16, 0.15, 0.2)
        materials: PrincipledMaterial {
            baseColor: "#e8cfae"
            roughness: 0.9
        }
    }
    Model {
        source: "#Sphere"
        position: Qt.vector3d(0, 23, 28)
        scale: Qt.vector3d(0.035, 0.035, 0.035)
        materials: PrincipledMaterial {
            baseColor: "#1e1814"
        }
    }
    Model {
        source: "#Sphere"
        position: Qt.vector3d(-6, 28, 22)
        scale: Qt.vector3d(0.03, 0.03, 0.03)
        materials: PrincipledMaterial {
            baseColor: "#1e1814"
        }
    }
    Model {
        source: "#Sphere"
        position: Qt.vector3d(6, 28, 22)
        scale: Qt.vector3d(0.03, 0.03, 0.03)
        materials: PrincipledMaterial {
            baseColor: "#1e1814"
        }
    }
    Model {
        source: "#Cube"
        position: Qt.vector3d(0, 12, 14)
        scale: Qt.vector3d(0.22, 0.16, 0.04)
        materials: PrincipledMaterial {
            baseColor: "#fbf6ea"
            roughness: 0.9
        }
    }
}
