import QtQuick
import QtQuick3D

Node {
    id: owl

    property real clock: 0

    PrincipledMaterial {
        id: plumage
        baseColor: "#9c7a5a"
        roughness: 0.9
    }
    PrincipledMaterial {
        id: pupil
        baseColor: "#1e1814"
        roughness: 0.2
    }

    Model {
        source: "#Sphere"
        y: 32
        scale: Qt.vector3d(0.32, 0.44, 0.3)
        materials: plumage
    }
    Model {
        source: "#Sphere"
        position: Qt.vector3d(0, 28, 9)
        scale: Qt.vector3d(0.22, 0.3, 0.14)
        materials: PrincipledMaterial {
            baseColor: "#e9d8bb"
            roughness: 0.9
        }
    }
    Node {
        y: 58
        eulerRotation.y: Math.sin(owl.clock * 0.35) * 55

        Model {
            source: "#Sphere"
            scale: Qt.vector3d(0.3, 0.26, 0.27)
            materials: plumage
        }
        Model {
            source: "#Sphere"
            position: Qt.vector3d(0, 0, 10)
            scale: Qt.vector3d(0.24, 0.19, 0.06)
            materials: PrincipledMaterial {
                baseColor: "#f3e6cf"
                roughness: 0.9
            }
        }
        Repeater3D {
            model: 2
            delegate: Node {
                required property int index
                readonly property real side: index === 0 ? -1 : 1
                position: Qt.vector3d(side * 6.5, 2, 13)
                Model {
                    source: "#Sphere"
                    scale: Qt.vector3d(0.075, 0.075, 0.04)
                    materials: PrincipledMaterial {
                        baseColor: "#fff9e6"
                    }
                }
                Model {
                    source: "#Sphere"
                    z: 1.5
                    scale: Qt.vector3d(0.035, 0.035, 0.03)
                    materials: pupil
                }
                Model {
                    source: "#Cylinder"
                    eulerRotation.x: 90
                    z: 1
                    scale: Qt.vector3d(0.09, 0.006, 0.09)
                    materials: PrincipledMaterial {
                        baseColor: "#3b3029"
                        roughness: 0.3
                    }
                }
            }
        }
        Model {
            source: "#Cone"
            position: Qt.vector3d(0, -4, 14)
            eulerRotation.x: 160
            scale: Qt.vector3d(0.03, 0.06, 0.03)
            materials: PrincipledMaterial {
                baseColor: "#e0a03c"
            }
        }
        Model {
            source: "#Cone"
            position: Qt.vector3d(-10, 12, 0)
            eulerRotation.z: 20
            scale: Qt.vector3d(0.04, 0.1, 0.04)
            materials: plumage
        }
        Model {
            source: "#Cone"
            position: Qt.vector3d(10, 12, 0)
            eulerRotation.z: -20
            scale: Qt.vector3d(0.04, 0.1, 0.04)
            materials: plumage
        }
    }
}
