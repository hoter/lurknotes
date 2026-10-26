"""Geometry math for placing the strip in X11 physical pixels."""

from lurkn.x11 import Rect, strip_rect


def test_strip_size_scales_to_physical_pixels():
    # Spec §6: strip is 10 x workarea-height logical px. X11 works in physical
    # pixels, so at scale 2 the surface must be 20 x 1856.
    workarea = Rect(66, 32, 1374, 928)

    strip = strip_rect(workarea, scale=2, width=10)

    assert (strip.width, strip.height) == (20, 1856)


def test_strip_is_flush_with_right_edge_and_workarea_top():
    # Workarea on this desktop starts at x=66 because of the dock, and at
    # y=32 below the GNOME top bar. The strip belongs at the workarea's right
    # edge and top, not at the screen's (spec §6/§13).
    workarea = Rect(66, 32, 1374, 928)

    strip = strip_rect(workarea, scale=2, width=10)

    assert (strip.x, strip.y) == (2860, 64)


def test_strip_geometry_at_scale_one():
    workarea = Rect(0, 32, 1440, 928)

    strip = strip_rect(workarea, scale=1, width=10)

    assert strip == Rect(x=1430, y=32, width=10, height=928)


def test_strip_geometry_at_fractional_scale():
    # 10 logical px at 150% is 15 physical px; the right edge moves to 1920.
    workarea = Rect(0, 32, 1280, 800)

    strip = strip_rect(workarea, scale=1.5, width=10)

    assert strip == Rect(x=1905, y=48, width=15, height=1200)
