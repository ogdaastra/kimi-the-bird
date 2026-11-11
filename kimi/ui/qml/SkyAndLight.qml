import QtQuick
import QtQuick3D
import Kimi3D

Node {
    id: sky

    required property var st
    property bool highQuality: true
    property vector3d center: Qt.vector3d(0, 0, 0)

    function direction(elevation, azimuth) {
        const e = elevation * Math.PI / 180
        const a = azimuth * Math.PI / 180
        return Qt.vector3d(Math.sin(a) * Math.cos(e), Math.sin(e), Math.cos(a) * Math.cos(e))
    }

    Model {
        position: Qt.vector3d(sky.center.x, 0, sky.center.z)
        castsShadows: false
        receivesShadows: false
        geometry: SkyDome {
            topColor: sky.st.skyTop
            horizonColor: sky.st.skyHorizon
            bottomColor: sky.st.skyBottom
        }
        materials: PrincipledMaterial {
            lighting: PrincipledMaterial.NoLighting
            vertexColorsEnabled: true
            cullMode: Material.NoCulling
        }
    }

    Model {
        source: "#Sphere"
        visible: sky.st.sunElevation > -4
        position: sky.center.plus(sky.direction(sky.st.sunElevation, sky.st.sunAzimuth).times(6000))
        scale: Qt.vector3d(4.2, 4.2, 4.2)
        castsShadows: false
        materials: PrincipledMaterial {
            lighting: PrincipledMaterial.NoLighting
            baseColor: "#fff3c4"
        }
    }

    Model {
        source: "#Sphere"
        visible: sky.st.night > 0.35
        position: sky.center.plus(sky.direction(38, sky.st.sunAzimuth + 160).times(6000))
        scale: Qt.vector3d(2.8, 2.8, 2.8)
        castsShadows: false
        materials: PrincipledMaterial {
            lighting: PrincipledMaterial.NoLighting
            baseColor: "#f4ecd0"
        }
    }

    Repeater3D {
        model: sky.st.night > 0.25 ? 150 : 0
        delegate: Model {
            required property int index
            readonly property real e: 12 + Math.abs(Math.sin(index * 12.9898) * 43758.5453 % 1) * 75
            readonly property real a: Math.abs(Math.sin(index * 78.233) * 12543.123 % 1) * 360
            source: "#Sphere"
            castsShadows: false
            position: sky.center.plus(sky.direction(e, a).times(6500))
            scale: Qt.vector3d(0.6 + index % 3 * 0.3, 0.6 + index % 3 * 0.3, 0.6 + index % 3 * 0.3)
            materials: PrincipledMaterial {
                lighting: PrincipledMaterial.NoLighting
                baseColor: "#fffbe8"
                opacity: Math.min(1, (sky.st.night - 0.25) * 2)
            }
        }
    }

    DirectionalLight {
        eulerRotation: Qt.vector3d(-Math.max(10, sky.st.sunElevation), sky.st.sunAzimuth, 0)
        color: sky.st.sunColor
        brightness: 0.12 + 0.95 * sky.st.sunBrightness
        ambientColor: Qt.rgba(Qt.color(sky.st.ambient).r * 0.3, Qt.color(sky.st.ambient).g * 0.3,
                              Qt.color(sky.st.ambient).b * 0.3, 1)
        castsShadow: sky.highQuality && sky.st.sunBrightness > 0.05
        shadowMapQuality: Light.ShadowMapQualityHigh
        shadowFactor: 55
        shadowBias: 30
        shadowMapFar: 3000
        csmNumSplits: 2
    }

    DirectionalLight {
        eulerRotation: Qt.vector3d(-38, sky.st.sunAzimuth + 160, 0)
        color: "#9fb4e8"
        brightness: sky.st.moonBrightness
    }
}
