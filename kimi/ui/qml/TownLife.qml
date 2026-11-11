import QtQuick
import QtQuick3D
import QtQuick3D.Particles3D

Node {
    id: life

    required property var st
    required property var lay
    property real clock: 0
    readonly property bool animate: !st.reduceMotion
    readonly property var canvasColours: ["#f2b8c6", "#9cc9dd", "#f7d35a", "#c9b3ec", "#a7cf8e"]

    Node {
        position: Qt.vector3d(life.lay.noticeBoard.x, 0, life.lay.noticeBoard.z)
        eulerRotation.y: life.lay.noticeBoard.facing

        Model {
            source: "#Cube"
            position: Qt.vector3d(15, 64, 3)
            eulerRotation.z: 5
            scale: Qt.vector3d(0.1, 0.12, 0.008)
            materials: PrincipledMaterial {
                baseColor: "#e9dcc0"
                roughness: 0.9
            }
        }
        Repeater3D {
            model: Math.min(6, life.st.unreadNotes)
            delegate: Model {
                required property int index
                source: "#Cube"
                position: Qt.vector3d(-18 + (index % 3) * 17, 86 - Math.floor(index / 3) * 19, 3.4)
                eulerRotation.z: (index * 37) % 14 - 7 + (life.animate ? Math.sin(life.clock * 3 + index) * 2 : 0)
                scale: Qt.vector3d(0.11, 0.13, 0.008)
                materials: PrincipledMaterial {
                    baseColor: "#fffaf0"
                    emissiveFactor: Qt.vector3d(0.15, 0.14, 0.1)
                    roughness: 0.9
                }
            }
        }
    }

    Node {
        position: Qt.vector3d(life.lay.easel.x, 0, life.lay.easel.z)
        eulerRotation.y: life.lay.easel.facing

        Repeater3D {
            model: Math.min(5, life.st.displayedCreations)
            delegate: Node {
                required property int index
                position: index === 0 ? Qt.vector3d(0, 50, 4) : Qt.vector3d(20 + index * 22, 16, -6)
                eulerRotation.x: index === 0 ? -8 : -14
                Model {
                    source: "#Cube"
                    scale: Qt.vector3d(0.36, 0.3, 0.025)
                    materials: PrincipledMaterial {
                        baseColor: "#8a5a3c"
                        roughness: 0.8
                    }
                }
                Model {
                    source: "#Cube"
                    z: 1.4
                    scale: Qt.vector3d(0.31, 0.25, 0.01)
                    materials: PrincipledMaterial {
                        baseColor: life.canvasColours[index % life.canvasColours.length]
                        roughness: 0.9
                    }
                }
            }
        }
    }

    Node {
        position: Qt.vector3d(life.lay.fountain.x, 0, life.lay.fountain.z)
        visible: life.animate

        Repeater3D {
            model: 8
            delegate: Model {
                required property int index
                readonly property real phase: (life.clock * 0.9 + index / 8) % 1
                readonly property real angle: index * Math.PI / 4
                source: "#Sphere"
                position: Qt.vector3d(Math.cos(angle) * (6 + phase * 26), 58 + 24 * Math.sin(phase * Math.PI) - phase * 34,
                                      Math.sin(angle) * (6 + phase * 26))
                scale: Qt.vector3d(0.045, 0.06, 0.045)
                castsShadows: false
                materials: PrincipledMaterial {
                    baseColor: "#cdeefa"
                    roughness: 0.1
                    opacity: 0.85
                }
            }
        }
    }

    ParticleSystem3D {
        position: Qt.vector3d(life.lay.chimney.x, life.lay.chimney.y, life.lay.chimney.z)
        running: life.animate

        ParticleEmitter3D {
            particle: smoke
            emitRate: 2.2
            lifeSpan: 5200
            particleScale: 0.12
            particleEndScale: 0.5
            velocity: VectorDirection3D {
                direction: Qt.vector3d(10, 30, 0)
                directionVariation: Qt.vector3d(6, 6, 6)
            }
        }
        ModelParticle3D {
            id: smoke
            maxAmount: 16
            fadeInDuration: 700
            fadeOutDuration: 2200
            delegate: Model {
                source: "#Sphere"
                castsShadows: false
                materials: PrincipledMaterial {
                    baseColor: "#ebebeb"
                    roughness: 1
                    opacity: 0.55
                }
            }
        }
    }

    ParticleSystem3D {
        position: Qt.vector3d(life.lay.shrub.x, 30, life.lay.shrub.z)
        running: life.animate && life.st.night > 0.55
        visible: running

        ParticleEmitter3D {
            particle: firefly
            emitRate: 5
            lifeSpan: 4200
            particleScale: 0.035
            shape: ParticleShape3D {
                type: ParticleShape3D.Sphere
                extents: Qt.vector3d(170, 40, 170)
            }
            velocity: VectorDirection3D {
                directionVariation: Qt.vector3d(14, 8, 14)
            }
        }
        ModelParticle3D {
            id: firefly
            maxAmount: 28
            fadeInDuration: 900
            fadeOutDuration: 900
            delegate: Model {
                source: "#Sphere"
                castsShadows: false
                materials: PrincipledMaterial {
                    lighting: PrincipledMaterial.NoLighting
                    baseColor: "#fff2a0"
                }
            }
        }
    }

    Repeater3D {
        model: life.st.night > 0.3 ? life.lay.lights : []
        delegate: PointLight {
            required property var modelData
            position: Qt.vector3d(modelData.x, modelData.y, modelData.z)
            color: "#ffcf8a"
            brightness: life.st.night * 1.8
            constantFade: 1
            linearFade: 0
            quadraticFade: 2.5
        }
    }
}
