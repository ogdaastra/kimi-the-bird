import QtQuick
import QtQuick3D
import QtQuick3D.Particles3D

Node {
    id: weather

    required property var st
    property bool highQuality: true
    property vector3d center: Qt.vector3d(0, 0, 0)
    property real clock: 0
    readonly property bool animate: !st.reduceMotion

    position: Qt.vector3d(center.x, 0, center.z)

    ParticleSystem3D {
        running: weather.animate && weather.st.rain > 0
        visible: running

        ParticleEmitter3D {
            particle: drop
            y: 650
            emitRate: weather.st.rain * (weather.highQuality ? 650 : 260)
            lifeSpan: 820
            shape: ParticleShape3D {
                type: ParticleShape3D.Cube
                extents: Qt.vector3d(520, 1, 520)
            }
            velocity: VectorDirection3D {
                direction: Qt.vector3d(-70, -900, 0)
                directionVariation: Qt.vector3d(15, 90, 15)
            }
        }
        ModelParticle3D {
            id: drop
            maxAmount: 700
            delegate: Model {
                source: "#Cube"
                castsShadows: false
                receivesShadows: false
                scale: Qt.vector3d(0.006, 0.13, 0.006)
                materials: PrincipledMaterial {
                    lighting: PrincipledMaterial.NoLighting
                    baseColor: "#c4d7ea"
                    opacity: 0.55
                }
            }
        }
    }

    ParticleSystem3D {
        running: weather.animate && weather.st.snow > 0
        visible: running

        ParticleEmitter3D {
            particle: flake
            y: 600
            emitRate: weather.highQuality ? 140 : 60
            lifeSpan: 6500
            particleScale: 0.035
            particleScaleVariation: 0.012
            shape: ParticleShape3D {
                type: ParticleShape3D.Cube
                extents: Qt.vector3d(520, 1, 520)
            }
            velocity: VectorDirection3D {
                direction: Qt.vector3d(0, -95, 0)
                directionVariation: Qt.vector3d(25, 15, 25)
            }
        }
        ModelParticle3D {
            id: flake
            maxAmount: 900
            delegate: Model {
                source: "#Sphere"
                castsShadows: false
                materials: PrincipledMaterial {
                    lighting: PrincipledMaterial.NoLighting
                    baseColor: "#ffffff"
                }
            }
        }
    }

    Repeater3D {
        model: weather.st.cloudiness > 0.15 ? 9 : 3
        delegate: Node {
            required property int index
            readonly property real orbit: 1550 + (index % 4) * 260
            readonly property real angle: index * 0.7 + (weather.animate ? weather.clock * 0.006 * (1 + index % 3 * 0.3) : 0)
            position: Qt.vector3d(-weather.center.x + Math.cos(angle) * orbit, 1150 + (index % 3) * 120,
                                  -weather.center.z + Math.sin(angle) * orbit)

            Repeater3D {
                model: 4
                delegate: Model {
                    required property int index
                    source: "#Sphere"
                    castsShadows: false
                    position: Qt.vector3d(index * 65 - 100, (index % 2) * 18, (index % 3) * 22)
                    scale: Qt.vector3d(1.1 - Math.abs(index - 1.5) * 0.2, 0.65, 0.9)
                    materials: PrincipledMaterial {
                        baseColor: Qt.rgba(1 - weather.st.night * 0.6 - weather.st.cloudiness * 0.25,
                                           1 - weather.st.night * 0.55 - weather.st.cloudiness * 0.22,
                                           1 - weather.st.night * 0.4 - weather.st.cloudiness * 0.18, 1)
                        roughness: 1
                        opacity: 0.8
                    }
                }
            }
        }
    }
}
