import QtQuick
import QtQuick3D
import Kimi3D

Node {
    id: town

    required property var st

    PrincipledMaterial {
        id: painted
        vertexColorsEnabled: true
        baseColor: "white"
        roughness: 0.92
        metalness: 0
    }

    Model {
        geometry: TownMesh { meshName: "terrain" }
        castsShadows: false
        materials: painted
    }
    Model {
        geometry: TownMesh { meshName: "paths" }
        castsShadows: false
        materials: painted
    }
    Model {
        geometry: TownMesh { meshName: "buildings" }
        pickable: true
        materials: painted
    }
    Model {
        geometry: TownMesh { meshName: "nature" }
        pickable: true
        materials: painted
    }
    Model {
        geometry: TownMesh { meshName: "curiosities" }
        pickable: true
        materials: painted
    }
    Model {
        geometry: TownMesh { meshName: "glow" }
        materials: PrincipledMaterial {
            baseColor: Qt.rgba(0.80 + 0.2 * town.st.night, 0.88 - 0.06 * town.st.night, 0.92 - 0.45 * town.st.night, 1)
            emissiveFactor: Qt.vector3d(1.0, 0.76, 0.4).times(town.st.night * 1.3)
            roughness: 0.25
        }
    }
    Model {
        geometry: TownMesh { meshName: "water" }
        castsShadows: false
        materials: PrincipledMaterial {
            vertexColorsEnabled: true
            baseColor: Qt.rgba(1 - 0.55 * town.st.night, 1 - 0.5 * town.st.night, 1 - 0.3 * town.st.night, 1)
            roughness: 0.12
            opacity: 0.92
        }
    }
}
