import unittest

from morphoscan_body import BodyComposition, Profile, impedance_channels

# Complete outputs frozen from the pinned WLA37 native dispatcher.
SYNTHETIC_REFERENCE = {
  "expected": {
    "result": {
      "bmi": 23.1,
      "bmr_kcal_per_day": 1724,
      "body_fat_percent": 16.4,
      "body_score": 80.0,
      "body_type_code": 5,
      "body_water_mass_kg": 45.97,
      "body_water_percent": 61.3,
      "bone_mass_kg": 4.2,
      "fat_control_kg": -1.5,
      "fat_free_mass_kg": 62.7,
      "fat_mass_kg": 12.3,
      "metabolic_age_years": 33,
      "muscle_control_kg": 0.0,
      "muscle_mass_kg": 58.5,
      "muscle_percent": 78.0,
      "protein_mass_kg": 12.53,
      "protein_percent": 16.7,
      "segments": {
        "left_arm": {
          "fat_mass_kg": 0.55,
          "fat_vs_standard_percent": 80.21,
          "muscle_mass_kg": 3.57,
          "muscle_vs_standard_percent": 107.23,
        },
        "left_leg": {
          "fat_mass_kg": 2.06,
          "fat_vs_standard_percent": 115.22,
          "muscle_mass_kg": 10.34,
          "muscle_vs_standard_percent": 111.15,
        },
        "right_arm": {
          "fat_mass_kg": 0.57,
          "fat_vs_standard_percent": 82.7,
          "muscle_mass_kg": 3.54,
          "muscle_vs_standard_percent": 106.32,
        },
        "right_leg": {
          "fat_mass_kg": 2.07,
          "fat_vs_standard_percent": 115.57,
          "muscle_mass_kg": 10.35,
          "muscle_vs_standard_percent": 111.24,
        },
        "trunk": {
          "fat_mass_kg": 6.58,
          "fat_vs_standard_percent": 144.3,
          "muscle_mass_kg": 27.32,
          "muscle_vs_standard_percent": 102.58,
        },
      },
      "skeletal_muscle_index_kg_m2": 8.6,
      "skeletal_muscle_mass_kg": 35.7,
      "skeletal_muscle_percent": 47.6,
      "standard_bmi": 22.0,
      "standard_bmr_kcal_per_day": 1678,
      "standard_body_fat_percent": 15.0,
      "standard_fat_free_mass_kg": 60.6,
      "standard_fat_mass_kg": 10.7,
      "standard_skeletal_muscle_kg": 34.0,
      "standard_weight_kg": 71.3,
      "subcutaneous_fat_percent": 11.8,
      "target_weight_kg": 73.5,
      "vendor_thresholds": {
        "bmi": {"max": 30.0, "min": 25.0},
        "bmr_kcal_per_day": {"max": 1845, "min": 1510},
        "body_fat_percent": {"max": 20.0, "min": 10.0},
        "body_water_mass_kg": {"max": 47.5, "min": 38.1},
        "bone_mass_kg": {"max": 4.3, "min": 3.5},
        "fat_mass_kg": {"max": 17.1, "min": 8.6},
        "muscle_mass_kg": {"max": 60.5, "min": 48.5},
        "protein_mass_kg": {"max": 13.0, "min": 10.4},
        "skeletal_muscle_kg": {"max": 37.4, "min": 30.6},
        "weight_kg": {"max": 82.0, "min": 60.6},
      },
      "visceral_fat_index": 3.0,
      "waist_hip_ratio": 0.84,
      "weight_control_kg": -1.5,
      "weight_vs_standard_percent": 105,
    }
  },
  "measurement": {
    "algorithm": 37,
    "impedance_values": [25, 300, 310, 260, 270, 18, 260, 270, 230, 240],
    "type": "measurement",
    "weight_kg": 75.0,
  },
  "profile": {
    "age": 35,
    "athlete": False,
    "bmi_standard": "who",
    "height_cm": 180,
    "sex": "male",
  },
}

REAL_REFERENCE = {
  "expected": {
    "result": {
      "bmi": 24.9,
      "bmr_kcal_per_day": 1790,
      "body_fat_percent": 18.4,
      "body_score": 81.0,
      "body_type_code": 5,
      "body_water_mass_kg": 48.17,
      "body_water_percent": 59.8,
      "bone_mass_kg": 4.4,
      "fat_control_kg": -4.0,
      "fat_free_mass_kg": 65.73,
      "fat_mass_kg": 14.82,
      "metabolic_age_years": 23,
      "muscle_control_kg": 0.0,
      "muscle_mass_kg": 61.38,
      "muscle_percent": 76.2,
      "protein_mass_kg": 13.13,
      "protein_percent": 16.3,
      "segments": {
        "left_arm": {
          "fat_mass_kg": 0.76,
          "fat_vs_standard_percent": 110.28,
          "muscle_mass_kg": 3.78,
          "muscle_vs_standard_percent": 109.72,
        },
        "left_leg": {
          "fat_mass_kg": 2.43,
          "fat_vs_standard_percent": 135.7,
          "muscle_mass_kg": 10.9,
          "muscle_vs_standard_percent": 113.19,
        },
        "right_arm": {
          "fat_mass_kg": 0.78,
          "fat_vs_standard_percent": 112.08,
          "muscle_mass_kg": 3.76,
          "muscle_vs_standard_percent": 109.21,
        },
        "right_leg": {
          "fat_mass_kg": 2.42,
          "fat_vs_standard_percent": 135.34,
          "muscle_mass_kg": 10.89,
          "muscle_vs_standard_percent": 113.12,
        },
        "trunk": {
          "fat_mass_kg": 8.0,
          "fat_vs_standard_percent": 175.43,
          "muscle_mass_kg": 28.67,
          "muscle_vs_standard_percent": 104.04,
        },
      },
      "skeletal_muscle_index_kg_m2": 9.1,
      "skeletal_muscle_mass_kg": 37.54,
      "skeletal_muscle_percent": 46.6,
      "standard_bmi": 22.0,
      "standard_bmr_kcal_per_day": 1678,
      "standard_body_fat_percent": 15.0,
      "standard_fat_free_mass_kg": 60.6,
      "standard_fat_mass_kg": 10.7,
      "standard_skeletal_muscle_kg": 34.0,
      "standard_weight_kg": 71.3,
      "subcutaneous_fat_percent": 13.2,
      "target_weight_kg": 76.5,
      "vendor_thresholds": {
        "bmi": {"max": 30.0, "min": 25.0},
        "bmr_kcal_per_day": {"max": 1845, "min": 1510},
        "body_fat_percent": {"max": 20.0, "min": 10.0},
        "body_water_mass_kg": {"max": 47.5, "min": 38.1},
        "bone_mass_kg": {"max": 4.3, "min": 3.5},
        "fat_mass_kg": {"max": 17.1, "min": 8.6},
        "muscle_mass_kg": {"max": 60.5, "min": 48.5},
        "protein_mass_kg": {"max": 13.0, "min": 10.4},
        "skeletal_muscle_kg": {"max": 37.4, "min": 30.6},
        "weight_kg": {"max": 82.0, "min": 60.6},
      },
      "visceral_fat_index": 5.0,
      "waist_hip_ratio": 0.84,
      "weight_control_kg": -4.1,
      "weight_vs_standard_percent": 113,
    }
  },
  "measurement": {
    "algorithm": 37,
    "impedance_values": [
      24.9,
      282.1,
      286.7,
      232.5,
      227.7,
      17.6,
      246.9,
      252.1,
      207.8,
      202.6,
    ],
    "type": "measurement",
    "weight_kg": 80.55,
  },
  "profile": {"age": 25, "height_cm": 180, "sex": "male"},
}


PROFILE_EXPECTED = {
  "female": {
    "body_score": 87.0,
    "body_type_code": 4,
    "fat_control_kg": 3.3,
    "metabolic_age_years": 32,
    "standard_bmi": 21.0,
    "standard_bmr_kcal_per_day": 1501,
    "standard_body_fat_percent": 23.0,
    "standard_fat_free_mass_kg": 52.4,
    "standard_fat_mass_kg": 15.6,
    "standard_skeletal_muscle_kg": 29.1,
    "standard_weight_kg": 68.0,
    "target_weight_kg": 78.3,
    "weight_control_kg": 3.3,
    "weight_vs_standard_percent": 110,
  },
  "male": {
    "body_score": 80.0,
    "body_type_code": 5,
    "fat_control_kg": -1.5,
    "metabolic_age_years": 33,
    "standard_bmi": 22.0,
    "standard_bmr_kcal_per_day": 1678,
    "standard_body_fat_percent": 15.0,
    "standard_fat_free_mass_kg": 60.6,
    "standard_fat_mass_kg": 10.7,
    "standard_skeletal_muscle_kg": 34.0,
    "standard_weight_kg": 71.3,
    "target_weight_kg": 73.5,
    "weight_control_kg": -1.5,
    "weight_vs_standard_percent": 105,
  },
}


class BodyCompositionTests(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    cls.calculator = BodyComposition()
    cls.measurement = SYNTHETIC_REFERENCE["measurement"]
    cls.profile = Profile(**SYNTHETIC_REFERENCE["profile"])

  def assert_result(self, actual, expected):
    self.assertIs(type(actual), type(expected))
    if isinstance(expected, dict):
      self.assertEqual(actual.keys(), expected.keys())
      for key in expected:
        with self.subTest(field=key):
          self.assert_result(actual[key], expected[key])
    elif isinstance(expected, (list, tuple)):
      self.assertEqual(len(actual), len(expected))
      for actual_item, expected_item in zip(actual, expected):
        self.assert_result(actual_item, expected_item)
    else:
      self.assertEqual(actual, expected)

  def test_complete_synthetic_reference(self):
    self.assert_result(
      self.calculator.calculate(self.measurement, self.profile),
      SYNTHETIC_REFERENCE["expected"]["result"],
    )

  def test_complete_real_reference(self):
    self.assert_result(
      self.calculator.calculate(
        REAL_REFERENCE["measurement"], Profile(**REAL_REFERENCE["profile"])
      ),
      REAL_REFERENCE["expected"]["result"],
    )

  def test_profile_matrix_and_athlete_equivalence(self):
    for sex, expected in PROFILE_EXPECTED.items():
      for standard, bounds in (
        ("asia", {"max": 28.0, "min": 24.0}),
        ("china", {"max": 25.0, "min": 23.0}),
        ("who", {"max": 30.0, "min": 25.0}),
      ):
        normal = None
        for athlete in (False, True):
          with self.subTest(sex=sex, standard=standard, athlete=athlete):
            result = self.calculator.calculate(
              self.measurement,
              Profile(
                age=35, athlete=athlete, bmi_standard=standard, height_cm=180, sex=sex
              ),
            )
            self.assert_result({key: result[key] for key in expected}, expected)
            self.assert_result(result["vendor_thresholds"]["bmi"], bounds)
            if athlete:
              # WLA37 accepts the setting but does not change its estimates.
              self.assert_result(result, normal)
            else:
              normal = result

  def test_repeated_estimates_do_not_compound_trunk_correction(self):
    original_impedances = self.measurement["impedance_values"].copy()
    first = self.calculator.calculate(self.measurement, self.profile)
    different = self.calculator.calculate(
      self.measurement, Profile(age=35, height_cm=180, sex="female")
    )
    self.assertEqual(different["target_weight_kg"], 78.3)
    self.assert_result(self.calculator.calculate(self.measurement, self.profile), first)
    self.assertEqual(self.measurement["impedance_values"], original_impedances)

  def test_contact_gates_report_status_two(self):
    for channel in range(10):
      values = self.measurement["impedance_values"].copy()
      values[channel] = 0.5 if channel % 5 == 0 else 99.0
      with (
        self.subTest(channel=channel),
        self.assertRaisesRegex(
          ValueError, r"^Vendor algorithm rejected the measurement \(status 2\)$"
        ),
      ):
        self.calculator.calculate(
          self.measurement | {"impedance_values": values}, self.profile
        )

  def test_negative_trunk_correction_reports_status_three(self):
    values = self.measurement["impedance_values"].copy()
    values[0] = 3.0
    with self.assertRaisesRegex(
      ValueError, r"^Vendor algorithm rejected the measurement \(status 3\)$"
    ):
      self.calculator.calculate(
        self.measurement | {"impedance_values": values}, self.profile
      )

  def test_nonfinite_computed_fields_are_rejected(self):
    # Finite inputs can still overflow the regression's intermediate products.
    measurement = self.measurement | {"impedance_values": [1e308] * 10}
    with self.assertRaisesRegex(
      ValueError, "^Vendor calculation returned a non-finite result$"
    ):
      self.calculator.calculate(measurement, self.profile)

  def test_channel_labels_follow_wire_order_not_report_order(self):
    channels = impedance_channels(self.measurement)
    self.assertEqual(channels["20"]["trunk"], 25)
    self.assertEqual(channels["20"]["left_arm"], 300)
    self.assertEqual(channels["20"]["right_arm"], 310)
    self.assertEqual(channels["100"]["left_leg"], 230)
    self.assertEqual(channels["100"]["right_leg"], 240)


if __name__ == "__main__":
  unittest.main()
