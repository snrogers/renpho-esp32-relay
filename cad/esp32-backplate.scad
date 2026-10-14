// Waveshare ESP32-S3-LCD-1.47 screw-on backplate. Units: mm.
// Source: official ESP32-S3-LCD-1.47.pdf in:
// https://files.waveshare.com/wiki/ESP32-S3-LCD-1.47/ESP32-S3-LCD-1.47_Structural_Drawings.zip
// Use the structural PDF, not the differently dimensioned wiki photograph.
// X=0 is the USB end; Y=0 is the PCB centreline; Z=0 is the print bed.
// Print flat, supports unnecessary. Assumes no soldered pin headers.
// Mount against the four existing metal mounting bosses, not PCB components.
// Hole callout is 4 x 2.00; confirm existing thread before selecting screws.
// Screw length must accommodate 3.0 mm of plastic plus safe boss engagement.
// Physical fit and fastener engagement have not been tested.

$fn = 64;

board_length       = 36.4;
board_width        = 20.33;
corner_radius      = 2.5;
edge_margin        = 1.0;
hole_clearance     = 2.4;
hole_column_pitch  = 32.0;
plate_thickness    = 2.0;
rear_hole_inset    = 1.98;
rear_hole_pitch    = 13.28;
show_board         = false;
show_dimensions    = true;
support_base_d     = 5.6;
support_height     = 1.0;
support_top_d      = 4.5;
usb_hole_pitch     = 16.32;

// Derived from the drawing, with unequal short-axis pitches.
rear_hole_x = board_length - rear_hole_inset;
usb_hole_x  = rear_hole_x - hole_column_pitch;
holes = [
  [usb_hole_x,  -usb_hole_pitch / 2],
  [usb_hole_x,   usb_hole_pitch / 2],
  [rear_hole_x, -rear_hole_pitch / 2],
  [rear_hole_x,  rear_hole_pitch / 2]
];

assert(support_top_d > hole_clearance + 2.0);
assert(support_height > (support_base_d - support_top_d) / 2);
assert(plate_thickness >= 2);

module footprint() {
  translate([board_length / 2, 0])
    offset(r = corner_radius)
      square([
        board_length + 2 * edge_margin - 2 * corner_radius,
        board_width + 2 * edge_margin - 2 * corner_radius
      ], center = true);
}

module backplate() {
  difference() {
    union() {
      linear_extrude(height = plate_thickness) footprint();
      for (p = holes)
        translate([p[0], p[1], plate_thickness - 0.1]) {
          // A short 45-degree root flare strengthens each support.
          cylinder(h = (support_base_d - support_top_d) / 2 + 0.1,
                   d1 = support_base_d, d2 = support_top_d);
          cylinder(h = support_height + 0.1, d = support_top_d);
        }
    }
    for (p = holes)
      translate([p[0], p[1], -0.1])
        cylinder(h = plate_thickness + support_height + 0.2,
                 d = hole_clearance);
  }
}

// Dimension graphics exist only in F5 preview, never in STL/F6 geometry.
module dimension_line(a, b, width = 0.15) {
  hull() {
    translate(a) circle(d = width, $fn = 12);
    translate(b) circle(d = width, $fn = 12);
  }
}

module dimension(a, b, label) {
  angle = atan2(b[1] - a[1], b[0] - a[0]);
  length = norm(b - a);
  translate(a) rotate(angle) {
    dimension_line([0, 0], [length, 0]);
    polygon([[0, 0], [1.1, 0.45], [1.1, -0.45]]);
    translate([length, 0])
      polygon([[0, 0], [-1.1, 0.45], [-1.1, -0.45]]);
    translate([length / 2, 0.8])
      text(label, size = 1.6, halign = "center");
  }
}

module dimensions() {
  xmin = -edge_margin;
  xmax = board_length + edge_margin;
  ymin = -board_width / 2 - edge_margin;
  ymax = board_width / 2 + edge_margin;
  color("#253b58")
    translate([0, 0, plate_thickness + support_height + 0.2])
      linear_extrude(height = 0.01) {
        // Overall footprint and longitudinal centre-to-centre spacing.
        for (x = [xmin, xmax])
          dimension_line([x, ymin - 0.5], [x, -18]);
        dimension([xmin, -17], [xmax, -17],
                  str(board_length + 2 * edge_margin, " mm"));
        for (y = [ymin, ymax])
          dimension_line([xmax + 0.5, y], [48, y]);
        dimension([47, ymin], [47, ymax],
                  str(board_width + 2 * edge_margin, " mm"));
        for (p = [holes[1], holes[3]])
          dimension_line(p, [p[0], 18]);
        dimension([usb_hole_x, 17], [rear_hole_x, 17],
                  str(hole_column_pitch, " C-C"));

        // The unequal transverse pitches identify the USB end.
        for (p = [holes[0], holes[1]])
          dimension_line(p, [-7, p[1]]);
        dimension([-6, -usb_hole_pitch / 2], [-6, usb_hole_pitch / 2],
                  str(usb_hole_pitch, " C-C"));
        for (p = [holes[2], holes[3]])
          dimension_line(p, [42, p[1]]);
        dimension([41, -rear_hole_pitch / 2], [41, rear_hole_pitch / 2],
                  str(rear_hole_pitch, " C-C"));

        translate([board_length / 2, 7])
          text(str("4 x Ø", hole_clearance, " through"),
               size = 1.6, halign = "center");
        dimension_line([board_length / 2 + 7, 7],
                       [rear_hole_x - hole_clearance / 2, rear_hole_pitch / 2]);
        translate([board_length / 2, 2])
          text(str("Plate: ", plate_thickness, " mm"),
               size = 1.6, halign = "center");
        translate([board_length / 2, -1])
          text(str("Risers: ", support_height, " mm"),
               size = 1.6, halign = "center");
        translate([board_length / 2, -4])
          text(str("Total: ", plate_thickness + support_height, " mm"),
               size = 1.6, halign = "center");
        translate([usb_hole_x, -13.5])
          text("USB END", size = 1.4, halign = "center");
        translate([board_length / 2, -22])
          text("All dimensions mm; C-C = centre-to-centre",
               size = 1.3, halign = "center");
      }
}

if ($preview && show_dimensions)
  dimensions();

backplate();

// Optional envelope only: not an exact component model and never exported.
// 2.5 mm is the rear mounting-boss projection shown in the vendor side view.
if (show_board)
  %translate([0, -board_width / 2,
              plate_thickness + support_height + 2.5])
    cube([board_length, board_width, 1.0]);
