"""Geometry math for placing the strip in X11 physical pixels."""

from lurkn.x11 import Rect, centered_position, panel_rect, strip_rect


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


def test_panel_sits_immediately_left_of_the_strip():
    # Spec §6: the 380-wide fan/panel is flush against the 10-wide strip at
    # the right edge. At scale 2 the panel is 760 physical px and ends where
    # the strip begins.
    workarea = Rect(66, 32, 1374, 928)

    panel = panel_rect(workarea, scale=2, width=380, strip_width=10)

    assert panel == Rect(x=2100, y=64, width=760, height=1856)


def test_panel_geometry_at_scale_one():
    workarea = Rect(0, 32, 1440, 928)

    panel = panel_rect(workarea, scale=1, width=380, strip_width=10)

    assert panel == Rect(x=1050, y=32, width=380, height=928)


def test_centered_window_sits_in_the_middle_of_the_workarea():
    # All Notes is 720 x 560 logical (spec §6). At scale 2 the visible size
    # is 1440 x 1120; GTK's shadow extents are outside the visible window, so
    # the X11 client origin moves left/up by them.
    workarea = Rect(66, 32, 1374, 928)

    position = centered_position(
        workarea,
        scale=2,
        width=720,
        height=560,
        frame_extents=(28, 28, 24, 34),
    )

    assert position == (758, 408)


def test_centered_window_without_frame_extents_is_flush_with_the_visible_rect():
    workarea = Rect(66, 32, 1374, 928)

    position = centered_position(workarea, scale=2, width=720, height=560)

    assert position == (786, 432)


def test_centered_window_at_scale_one():
    workarea = Rect(0, 32, 1440, 928)

    position = centered_position(workarea, scale=1, width=720, height=560)

    assert position == (360, 216)


def test_centered_window_at_fractional_scale():
    workarea = Rect(0, 32, 1280, 800)

    position = centered_position(workarea, scale=1.5, width=720, height=560)

    assert position == (420, 228)
