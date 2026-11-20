from cyclesense.basemap import (
    assemble_context_layers,
    intersects_bbox,
    polygon_kind,
    polygons_from_rings,
    stitch_rings,
)


def test_polygon_kind_prefers_water_then_park_then_building() -> None:
    assert polygon_kind({"natural": "water"}) == "water"
    assert polygon_kind({"leisure": "park"}) == "green"
    assert polygon_kind({"building": "yes"}) == "building"
    assert polygon_kind({"highway": "residential"}) is None
    assert polygon_kind({"building": "no"}) is None


def test_stitch_rings_joins_a_split_square() -> None:
    rings = stitch_rings(
        [
            [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)],
            [(1.0, 1.0), (0.0, 1.0), (0.0, 0.0)],
        ]
    )
    assert len(rings) == 1
    assert rings[0][0] == rings[0][-1]
    assert intersects_bbox(rings[0], (0.0, 0.0, 1.0, 1.0))


def test_polygons_keep_an_inner_ring_as_a_hole() -> None:
    outer = [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0), (0.0, 0.0)]
    inner = [(1.0, 1.0), (2.0, 1.0), (2.0, 2.0), (1.0, 2.0), (1.0, 1.0)]
    geometries = polygons_from_rings([outer], [inner])
    assert geometries[0]["type"] == "Polygon"
    assert len(geometries[0]["coordinates"]) == 2


def test_assemble_context_layers_keeps_named_streets_and_buildings() -> None:
    building = [(12.57, 55.676), (12.571, 55.676), (12.571, 55.677), (12.57, 55.677), (12.57, 55.676)]
    layers = assemble_context_layers(
        [
            {"id": 1, "coords": building, "closed": True, "tags": {"building": "yes", "name": "Test House"}},
            {
                "id": 2,
                "coords": [(12.57, 55.676), (12.572, 55.675)],
                "closed": False,
                "tags": {"highway": "residential", "name": "Testvej"},
            },
        ],
        [],
        (12.56, 55.67, 12.58, 55.68),
    )
    assert layers["buildings"]["features"][0]["properties"]["name"] == "Test House"
    assert layers["streets"]["features"][0]["properties"]["name"] == "Testvej"
    assert layers["labels"]["features"][0]["properties"]["name"] == "Testvej"


def test_relation_members_are_not_drawn_twice() -> None:
    outer = [(0.0, 0.0), (3.0, 0.0), (3.0, 3.0), (0.0, 3.0), (0.0, 0.0)]
    layers = assemble_context_layers(
        [{"id": 7, "coords": outer, "closed": True, "tags": {"natural": "water", "name": "Way lake"}}],
        [
            {
                "tags": {"natural": "water", "name": "Relation lake"},
                "members": [{"ref": 7, "role": "outer"}],
            }
        ],
        (0.0, 0.0, 3.0, 3.0),
    )
    names = [feature["properties"]["name"] for feature in layers["water"]["features"]]
    assert names == ["Relation lake"]
