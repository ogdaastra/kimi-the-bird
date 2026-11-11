import QtQuick
import QtQuick3D

Node {
    id: cat

    property real clock: 0

    PrincipledMaterial {
        id: coat
        baseColor: "#2f2e36"
        roughness: 0.75
    }

    Model {
        source: "#Sphere"
        y: 16
        scale: Qt.vector3d(0.24, 0.26, 0.34)
        materials: coat
    }
    Node {
        position: Qt.vector3d(0, 34, 10)
        eulerRotation.y: Math.sin(cat.clock * 0.5) * 18

        Model {
            source: "#Sphere"
            scale: Qt.vector3d(0.2, 0.18, 0.18)
            materials: coat
        }
        Model {
            source: "#Cone"
            position: Qt.vector3d(-6, 8, 0)
            eulerRotation.z: 12
            scale: Qt.vector3d(0.05, 0.08, 0.04)
            materials: coat
        }
        Model {
            source: "#Cone"
            position: Qt.vector3d(6, 8, 0)
            eulerRotation.z: -12
            scale: Qt.vector3d(0.05, 0.08, 0.04)
            materials: coat
        }
        Model {
            source: "#Sphere"
            position: Qt.vector3d(-4, 1, 8.5)
            scale: Qt.vector3d(0.035, 0.028, 0.02)
            materials: PrincipledMaterial {
                baseColor: "#f7d35a"
                emissiveFactor: Qt.vector3d(0.4, 0.33, 0.1)
            }
        }
        Model {
            source: "#Sphere"
            position: Qt.vector3d(4, 1, 8.5)
            scale: Qt.vector3d(0.035, 0.028, 0.02)
            materials: PrincipledMaterial {
                baseColor: "#f7d35a"
                emissiveFactor: Qt.vector3d(0.4, 0.33, 0.1)
            }
        }
    }
    Node {
        position: Qt.vector3d(0, 10, -16)
        eulerRotation.x: -50
        eulerRotation.z: Math.sin(cat.clock * 1.4) * 25

        Model {
            source: "#Cylinder"
            y: 14
            scale: Qt.vector3d(0.04, 0.3, 0.04)
            materials: coat
        }
    }
}
