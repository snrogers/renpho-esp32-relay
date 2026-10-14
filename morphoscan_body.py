"""Local Python implementation compatible with MorphoScan 1.9.8 / WLA37.

Vendor BIA estimates are not diagnostic measurements. Arithmetic deliberately
preserves the native model's binary32 intermediates and decimal truncation.
"""

import math
import struct
from dataclasses import dataclass

BMI_STANDARDS = {"asia": 1, "china": 2, "who": 0}

# Wire order, independently traced through the app's impedance report.
CHANNEL_ORDER = ("trunk", "left_arm", "right_arm", "left_leg", "right_leg")
FREQUENCIES_KHZ = (20, 100)


@dataclass(frozen=True, kw_only=True)
class Profile:
  # fmt: off
  age:          int
  athlete:      bool = False
  bmi_standard: str  = "who"
  height_cm:    int
  sex:          str
  # fmt: on

  def __post_init__(self):
    if not isinstance(self.age, int) or not 10 <= self.age <= 80:
      raise ValueError("RENPHO specifies body-fat estimates for ages 10 through 80")
    if not isinstance(self.height_cm, int) or not 100 <= self.height_cm <= 220:
      raise ValueError("WLA37 requires height in whole centimetres, from 100 to 220")
    if self.sex not in ("female", "male"):
      raise ValueError("The vendor model requires a female or male sex setting")
    if self.bmi_standard not in BMI_STANDARDS:
      raise ValueError("BMI standard must be asia, china, or who")


def impedance_channels(measurement: dict) -> dict:
  if measurement.get("algorithm") != 37:
    raise ValueError("Interpretation is verified only for MorphoScan algorithm 37")
  values = measurement.get("impedance_values", ())
  if len(values) != 10 or any(
    not math.isfinite(value) or value < 0 for value in values
  ):
    raise ValueError("Expected ten finite, nonnegative segment impedance readings")
  return {
    str(frequency): dict(zip(CHANNEL_ORDER, values[index * 5 : index * 5 + 5]))
    for index, frequency in enumerate(FREQUENCIES_KHZ)
  }


# WLA37 common helpers from libICBodyFatAlgorithms.so (ELF offsets).
# getStandardBMILower 0x19304  Upper 0x19328  BMI 0x1934c
# Weight 0x19d04  BFM 0x19d40  FFM 0x19da0  SMM 0x19e00
# Score 0x1b078  BMR 0x1b150  predictWHR 0x1b3d4  calcWHR 0x1b614
# getBodyType 0x1b6f4  WLA37 getBodyType_570 0x625a4
# ceil 0x62084 (fmodf)  dispatcher 0x1ce40 (fmod)
# Native sex 1=male 2=female. getStandard*(height, age, sex[, bmi_standard]).
# Sex index for 0x929d0/0x929e0: cset eq sex==1 -> male uses 0.15 BFM / 0.85 FFM.


# (max_height_inclusive, female, male); exact f32 literals from rodata.
_SMM_CHILD = (
  (100, 6.239999771118164, 6.28000020980835),
  (101, 6.309999942779541, 6.349999904632568),
  (102, 6.460000038146973, 6.420000076293945),
  (103, 6.539999961853027, 6.619999885559082),
  (104, 6.630000114440918, 6.71999979019165),
  (105, 6.730000019073486, 6.820000171661377),
  (106, 6.840000152587891, 6.920000076293945),
  (107, 6.949999809265137, 7.039999961853027),
  (108, 7.070000171661377, 7.159999847412109),
  (109, 7.199999809265137, 7.300000190734863),
  (110, 7.340000152587891, 7.519999980926514),
  (111, 7.489999771118164, 7.670000076293945),
  (112, 7.639999866485596, 7.829999923706055),
  (113, 7.809999942779541, 8.0),
  (114, 7.980000019073486, 8.180000305175781),
  (115, 8.15999984741211, 8.359999656677246),
  (116, 8.350000381469727, 8.550000190734863),
  (117, 8.539999961853027, 8.760000228881836),
  (118, 8.75, 8.970000267028809),
  (119, 8.960000038146973, 9.180000305175781),
  (120, 9.180000305175781, 9.40999984741211),
  (121, 9.40999984741211, 9.649999618530273),
  (122, 9.649999618530273, 9.890000343322754),
  (123, 9.899999618530273, 10.140000343322754),
  (124, 10.149999618530273, 10.40999984741211),
  (125, 10.420000076293945, 10.680000305175781),
  (126, 10.5600004196167, 10.949999809265137),
  (127, 10.84000015258789, 11.239999771118164),
  (128, 11.119999885559082, 11.539999961853027),
  (129, 11.420000076293945, 11.84000015258789),
  (130, 11.720000267028809, 12.15999984741211),
  (131, 12.029999732971191, 12.479999542236328),
  (132, 12.199999809265137, 12.8100004196167),
  (133, 12.520000457763672, 13.140000343322754),
  (134, 12.850000381469727, 13.489999771118164),
  (135, 13.1899995803833, 13.850000381469727),
  (136, 13.529999732971191, 14.210000038146973),
  (137, 13.890000343322754, 14.579999923706055),
  (138, 14.069999694824219, 14.960000038146973),
  (139, 14.4399995803833, 15.34000015258789),
  (140, 14.8100004196167, 15.739999771118164),
  (141, 15.180000305175781, 16.139999389648438),
  (142, 15.569999694824219, 16.549999237060547),
  (143, 15.960000038146973, 16.959999084472656),
  (144, 16.15999984741211, 17.389999389648438),
  (145, 16.559999465942383, 17.81999969482422),
  (146, 16.959999084472656, 18.25),
  (147, 17.3799991607666, 18.700000762939453),
  (148, 17.790000915527344, 19.149999618530273),
  (149, 18.219999313354492, 19.610000610351562),
  (150, 18.649999618530273, 20.06999969482422),
  (151, 19.18000030517578, 20.790000915527344),
  (152, 19.610000610351562, 21.260000228881836),
  (153, 20.049999237060547, 21.719999313354492),
  (154, 20.479999542236328, 22.190000534057617),
  (155, 20.6299991607666, 22.65999984741211),
  (156, 21.06999969482422, 23.139999389648438),
  (157, 21.510000228881836, 23.6200008392334),
  (158, 21.639999389648438, 24.100000381469727),
  (159, 22.079999923706055, 24.579999923706055),
  (160, 22.510000228881836, 25.059999465942383),
  (161, 22.950000762939453, 25.540000915527344),
  (162, 23.389999389648438, 26.030000686645508),
  (163, 23.829999923706055, 26.510000228881836),
  (164, 24.270000457763672, 27.0),
  (165, 24.709999084472656, 27.479999542236328),
  (166, 25.149999618530273, 27.969999313354492),
  (167, 25.579999923706055, 28.450000762939453),
  (168, 26.020000457763672, 28.93000030517578),
  (169, 26.450000762939453, 29.40999984741211),
  (170, 26.889999389648438, 29.889999389648438),
  (171, 27.31999969482422, 30.360000610351562),
  (172, 27.739999771118164, 30.829999923706055),
  (173, 28.15999984741211, 31.299999237060547),
  (174, 28.579999923706055, 31.760000228881836),
  (175, 29.0, 32.220001220703125),
  (176, 29.40999984741211, 32.66999816894531),
  (177, 29.809999465942383, 33.119998931884766),
  (178, 30.209999084472656, 33.560001373291016),
  (179, 30.600000381469727, 33.9900016784668),
  (250, 30.989999771118164, 34.41999816894531),
)
_SMM_ADULT = (
  (123, 12.539999961853027, 14.819999694824219),
  (124, 12.779999732971191, 15.09000015258789),
  (125, 13.020000457763672, 15.369999885559082),
  (126, 13.260000228881836, 15.649999618530273),
  (127, 13.5, 15.930000305175781),
  (128, 13.75, 16.209999084472656),
  (129, 13.989999771118164, 16.5),
  (130, 14.239999771118164, 16.780000686645508),
  (131, 14.489999771118164, 17.06999969482422),
  (132, 14.75, 17.3700008392334),
  (133, 15.0, 17.65999984741211),
  (134, 15.260000228881836, 17.959999084472656),
  (135, 15.520000457763672, 18.260000228881836),
  (136, 15.779999732971191, 18.559999465942383),
  (137, 16.040000915527344, 18.860000610351562),
  (138, 16.299999237060547, 19.170000076293945),
  (139, 16.56999969482422, 19.469999313354492),
  (140, 16.84000015258789, 19.780000686645508),
  (141, 17.110000610351562, 20.100000381469727),
  (142, 17.3799991607666, 20.40999984741211),
  (143, 17.649999618530273, 20.729999542236328),
  (144, 17.93000030517578, 21.049999237060547),
  (145, 18.209999084472656, 21.3700008392334),
  (146, 18.489999771118164, 21.690000534057617),
  (147, 18.770000457763672, 22.020000457763672),
  (148, 19.049999237060547, 22.34000015258789),
  (149, 19.34000015258789, 22.670000076293945),
  (150, 19.6200008392334, 23.010000228881836),
  (151, 19.90999984741211, 23.34000015258789),
  (152, 20.200000762939453, 23.68000030517578),
  (153, 20.5, 24.020000457763672),
  (154, 20.790000915527344, 24.360000610351562),
  (155, 21.09000015258789, 24.700000762939453),
  (156, 21.389999389648438, 25.049999237060547),
  (157, 21.690000534057617, 25.389999389648438),
  (158, 21.989999771118164, 25.739999771118164),
  (159, 22.299999237060547, 26.100000381469727),
  (160, 22.600000381469727, 26.450000762939453),
  (161, 22.90999984741211, 26.809999465942383),
  (162, 23.219999313354492, 27.170000076293945),
  (163, 23.530000686645508, 27.530000686645508),
  (164, 23.850000381469727, 27.889999389648438),
  (165, 24.15999984741211, 28.260000228881836),
  (166, 24.479999542236328, 28.6200008392334),
  (167, 24.799999237060547, 28.989999771118164),
  (169, 25.450000762939453, 29.739999771118164),
  (170, 25.770000457763672, 30.1200008392334),
  (171, 26.100000381469727, 30.5),
  (172, 26.43000030517578, 30.8799991607666),
  (173, 26.760000228881836, 31.260000228881836),
  (174, 27.100000381469727, 31.649999618530273),
  (175, 27.43000030517578, 32.029998779296875),
  (176, 27.770000457763672, 32.43000030517578),
  (177, 28.110000610351562, 32.81999969482422),
  (178, 28.450000762939453, 33.209999084472656),
  (179, 28.790000915527344, 33.61000061035156),
  (180, 29.139999389648438, 34.0099983215332),
  (181, 29.479999542236328, 34.40999984741211),
  (182, 29.829999923706055, 34.810001373291016),
  (183, 30.18000030517578, 35.220001220703125),
  (184, 30.540000915527344, 35.630001068115234),
  (185, 30.889999389648438, 36.040000915527344),
  (186, 31.25, 36.45000076293945),
  (187, 31.600000381469727, 36.86000061035156),
  (188, 31.969999313354492, 37.279998779296875),
  (189, 32.33000183105469, 37.70000076293945),
  (250, 32.689998626708984, 38.119998931884766),
)
_BMI_CHILD = (
  (85, 23.399999618530273),
  (86, 22.700000762939453),
  (87, 22.0),
  (88, 21.299999237060547),
  (89, 20.700000762939453),
  (90, 20.200000762939453),
  (91, 19.600000381469727),
  (92, 19.200000762939453),
  (93, 18.700000762939453),
  (95, 18.299999237060547),
  (96, 17.700000762939453),
  (97, 17.299999237060547),
  (98, 17.0),
  (99, 16.799999237060547),
  (100, 16.5),
  (101, 16.299999237060547),
  (102, 16.200000762939453),
  (103, 16.100000381469727),
  (104, 15.899999618530273),
  (105, 15.699999809265137),
  (106, 15.600000381469727),
  (108, 15.5),
  (110, 15.399999618530273),
  (116, 15.5),
  (118, 15.600000381469727),
  (120, 15.699999809265137),
  (121, 15.800000190734863),
  (123, 15.899999618530273),
  (124, 16.100000381469727),
  (125, 16.200000762939453),
  (126, 16.299999237060547),
  (127, 16.399999618530273),
  (128, 16.5),
  (129, 16.600000381469727),
  (130, 16.799999237060547),
  (131, 16.899999618530273),
  (132, 17.0),
  (133, 17.100000381469727),
  (134, 17.299999237060547),
  (135, 17.5),
  (136, 17.600000381469727),
  (137, 17.700000762939453),
  (138, 17.899999618530273),
  (139, 18.0),
  (140, 18.200000762939453),
  (141, 18.299999237060547),
  (142, 18.5),
  (143, 18.600000381469727),
  (144, 18.700000762939453),
  (145, 18.899999618530273),
  (146, 19.100000381469727),
  (147, 19.200000762939453),
  (148, 19.399999618530273),
  (149, 19.5),
  (150, 19.600000381469727),
  (151, 19.799999237060547),
  (152, 19.899999618530273),
  (153, 20.100000381469727),
  (154, 20.200000762939453),
  (155, 20.299999237060547),
  (156, 20.399999618530273),
  (157, 20.600000381469727),
  (158, 20.700000762939453),
  (159, 20.799999237060547),
  (160, 20.899999618530273),
  (161, 21.0),
  (162, 21.100000381469727),
  (163, 21.200000762939453),
  (164, 21.299999237060547),
  (165, 21.399999618530273),
  (166, 21.5),
  (167, 21.600000381469727),
  (168, 21.700000762939453),
  (169, 21.799999237060547),
  (171, 21.899999618530273),
  (10000, 22.0),
)
_WHR_COEF = (
  0.004613923840224743,
  1.454566609027097e-05,
  -2.1142072000657208e-05,
  -0.0007152269245125353,
  -0.006957625970244408,
  -0.002303469693288207,
  0.004452168941497803,
  0.014823568053543568,
  0.0022643720731139183,
  -0.010098490864038467,
  0.002619063016027212,
  -0.0037165714893490076,
  -0.0023263159673660994,
  0.011014733463525772,
  0.13338060677051544,
  -0.5725440382957458,
  -2.739877223968506,
  -0.5594097375869751,
  1.8687069416046143,
  -0.1797514259815216,
  0.5277798771858215,
  0.5406519174575806,
  -2.0791192054748535,
  7.878778706071898e-05,
  -3.554136856109835e-05,
  0.00017592347285244614,
  4.8191061068791896e-05,
  -0.00012233802408445626,
  -9.596181917004287e-05,
  3.8060684346419293e-06,
  -1.9787330529652536e-05,
  0.00017278089944738895,
  1.169865369796753,
  0.918518602848053,
  -0.007019151002168655,
  0.20594455301761627,
  -0.10937649011611938,
  -0.9890053868293762,
  -0.7043123245239258,
  -0.3479173183441162,
  0.0001994896010728553,
)
_WHR_INTERCEPT = 1.3684715032577515
_BMI_LOWER = (24.0, 23.0, 24.0)
_BMI_UPPER = (28.0, 25.0, 27.0)
_BFM_COEF = (0.23, 0.15)  # female, male  0x929d0
_FFM_COEF = (0.77, 0.85)  # female, male  0x929e0


def _f32(x):
  try:
    return struct.unpack("<f", struct.pack("<f", float(x)))[0]
  except OverflowError:
    return math.copysign(math.inf, x)


def _male(sex):
  return int(sex) == 1


def _round_f32(value):
  """WLA37 ceil at 0x62084: fmodf, strict > half, truncate toward zero."""
  single = _f32(value)
  if not math.isfinite(single):
    raise ValueError("Vendor calculation returned a non-finite result")
  tenths = _f32(math.fmod(single, 1.0) * 10.0)
  remainder = _f32(math.fmod(tenths, 1.0))
  if remainder > 0.5:
    tenths = _f32(tenths + 1.0)
  return _f32(_f32(_f32(int(tenths)) / 10.0) + _f32(int(value)))


def _round_f64(value):
  """Dispatcher rounding keeps the first remainder in binary64, unlike WLA37."""
  if not math.isfinite(value):
    raise ValueError("Vendor calculation returned a non-finite result")
  tenths = _f32(_f32(math.fmod(value, 1.0)) * 10.0)
  remainder = _f32(math.fmod(tenths, 1.0))
  if remainder > 0.5:
    tenths = _f32(tenths + 1.0)
  return _f32(_f32(_f32(int(tenths)) / 10.0) + _f32(int(value)))


def _h100_sq(height):
  s1 = _f32(float(height) / 100.0)
  return _f32(s1 * s1)


def _lookup(table, height):
  for row in table:
    if height <= row[0]:
      return row[1:]
  return table[-1][1:]


def _standard_bmi_lower(bmi_standard):
  i = int(bmi_standard) - 1
  if i < 0 or i > 2:
    return _f32(25.0)
  return _f32(_BMI_LOWER[i])


def _standard_bmi_upper(bmi_standard):
  i = int(bmi_standard) - 1
  if i < 0 or i > 2:
    return _f32(30.0)
  return _f32(_BMI_UPPER[i])


def _standard_bmi(height, age, sex, bmi_standard):
  if int(age) > 17:
    return _f32(22.0 if _male(sex) else 21.0)
  return _f32(_lookup(_BMI_CHILD, height)[0])


def _standard_weight(height, age, sex, bmi_standard):
  return _f32(_h100_sq(height) * _standard_bmi(height, age, sex, bmi_standard))


def _standard_bfm(height, age, sex, bmi_standard):
  h2b = _f32(_h100_sq(height) * _standard_bmi(height, age, sex, bmi_standard))
  return _f32(float(h2b) * float(_BFM_COEF[_male(sex)]))


def _standard_ffm(height, age, sex, bmi_standard):
  h2b = _f32(_h100_sq(height) * _standard_bmi(height, age, sex, bmi_standard))
  return _f32(float(h2b) * float(_FFM_COEF[_male(sex)]))


def _standard_smm(height, age, sex):
  table = _SMM_ADULT if int(age) > 17 else _SMM_CHILD
  female, male = _lookup(table, height)
  return _f32(male if _male(sex) else female)


def _standard_bmr(height, age, sex, bmi_standard):
  h2b = _f32(_h100_sq(height) * _standard_bmi(height, age, sex, bmi_standard))
  ffm = _f32(float(h2b) * float(_FFM_COEF[_male(sex)]))
  acc = _f32(float(ffm) * 21.6 + 370.0)
  return int(acc) if math.isfinite(acc) else 0


def _score(height, weight_f32, age, sex, bfp_f32, bmi_standard):
  w = _f32(weight_f32)
  fat_mass = _f32(float(_f32(bfp_f32)) / 100.0 * float(w))
  ffm = _f32(w - fat_mass)
  h2b = _f32(_h100_sq(height) * _standard_bmi(height, age, sex, bmi_standard))
  idx = _male(sex)
  std_bfm = _f32(float(h2b) * float(_BFM_COEF[idx]))
  std_ffm = _f32(float(h2b) * float(_FFM_COEF[idx]))
  d_fat = _f32(fat_mass - std_bfm)
  d_ffm = _f32(ffm - std_ffm)
  coef = float(0.983 if d_fat < 0.0 else -0.958)
  acc = float(d_ffm) + 80.0 + coef * float(d_fat)
  return int(acc) if math.isfinite(acc) else 0


def _waist_hip_ratio(weight, height, bmi_f32, imps):
  # predictWHR 0x1b3d4 layout (41 f32, 0xa4 bytes):
  # 0 w, 1 w^2, 2 h^2, 3 h, 4 bmi(s0),
  # 5-13 imps 1,2,0,3,4,6,7,8,9 (skip 5),
  # 14-22 those / h,
  # 23-31 bmi * those,
  # 32-40 h / those.
  # calcWHR 0x1b614: +(-0.015); >1.1 -> 0.6; <0.7 -> 0.7.
  h = _f32(int(height))
  w = _f32(weight)
  bmi = _f32(bmi_f32)
  zs = [_f32(imps[i]) for i in (1, 2, 0, 3, 4, 6, 7, 8, 9)]
  feats = [w, _f32(w * w), _f32(h * h), h, bmi]
  feats.extend(zs)
  feats.extend(_f32(z / h) for z in zs)
  feats.extend(_f32(bmi * z) for z in zs)
  feats.extend(_f32(h / z) for z in zs)
  acc = _f32(0.0)
  for i, feat in enumerate(feats):
    acc = _f32(acc + _f32(_f32(_WHR_COEF[i]) * feat))
  acc = _f32(acc + _f32(_WHR_INTERCEPT))
  thousand = _f32(1000.0)
  frac = math.fmod(float(acc), 1.0)
  scaled = _f32(_f32(frac) * thousand)
  rem = _f32(math.fmod(float(scaled), 1.0))
  cand = _f32(scaled + _f32(1.0)) if rem > _f32(0.5) else scaled
  w9 = int(cand) if math.isfinite(cand) else 0
  w8 = int(acc) if math.isfinite(acc) else 0
  pred = _f32(_f32(_f32(w9) / thousand) + _f32(w8))
  v = _f32(float(pred) + -0.015)
  dv = float(v)
  if dv > 1.1:
    return _f32(0.6000000238418579)
  if dv < 0.7:
    return _f32(0.699999988079071)
  return v


def _body_type(sex, bmi, fat):
  male = _male(sex)
  lo_f = 10.0 if male else 18.0
  hi_f = 20.0 if male else 28.0
  mid_f = 15.0 if male else 23.0
  b = float(bmi)
  f = float(fat)
  if b < 18.5 and f < lo_f:
    return 0
  if f < hi_f and b < 18.5 and f >= lo_f:
    return 1
  in_18_22 = b >= 18.5 and b < 22.0
  if in_18_22 and f < lo_f:
    return 2
  in_lo_mid = f >= lo_f and f < mid_f
  if in_18_22 and in_lo_mid:
    return 3
  in_22_25 = b >= 22.0 and b < 25.0
  if in_22_25 and f < mid_f:
    return 4
  if f < hi_f and b >= 18.5 and b < 25.0 and f >= mid_f:
    return 5
  if b >= 25.0 and f < mid_f:
    return 6
  if f < hi_f and b >= 25.0 and f >= mid_f:
    return 7
  if b >= 25.0 and f >= hi_f:
    return 8
  if in_22_25 and f >= hi_f:
    return 9
  if f >= hi_f and b < 22.0:
    return 10
  return 0


def _postprocess(height, sex, age, bmi_standard, weight, bmi, body_fat_percent):
  # Algo field 36 != 0x17/0x18, so 0x1d418.. runs. Copies WLA37 then
  # rewrites standards with fmod (_round_f64), then target/control/score.
  std_w = _round_f64(_standard_weight(height, age, sex, bmi_standard))
  std_bmi = _round_f64(_standard_bmi(height, age, sex, bmi_standard))
  std_smm = _round_f64(_standard_smm(height, age, sex))
  std_bfm = _round_f64(_standard_bfm(height, age, sex, bmi_standard))
  std_ffm = _round_f64(_standard_ffm(height, age, sex, bmi_standard))
  std_bmr = _standard_bmr(height, age, sex, bmi_standard)
  pct = _round_f64(weight / std_w * 100.0)
  ratio = int(_f32(pct)) if math.isfinite(pct) else 0
  male = _male(sex)
  fat_mass = weight * body_fat_percent / 100.0
  ffm = weight - fat_mass
  fat_ctrl = _round_f64(std_bfm - fat_mass)
  mus_ctrl = max(_round_f64(std_ffm - ffm), 0.0)
  wt_ctrl = fat_ctrl + mus_ctrl
  tgt = _round_f64(weight + wt_ctrl)
  score = _score(height, _f32(weight), age, sex, _f32(body_fat_percent), bmi_standard)
  score = max(20, score)
  k_lo, k_hi = (0.8, 1.6) if male else (0.87, 1.395)
  h2m = float(height * height) / 10000.0
  wt_lo = h2m * std_bmi * 0.85
  wt_hi = h2m * std_bmi * 1.15
  fat_lo_m = k_lo * std_bfm
  fat_hi_m = k_hi * std_bfm
  smm_lo = std_smm * 0.9
  smm_hi = std_smm * 1.1
  bmr_lo = int(float(std_bmr) * 0.9)
  bmr_hi = int(float(std_bmr) * 1.1)
  d_lo = wt_lo - fat_lo_m
  d_hi = wt_hi - fat_hi_m
  return {
    "standard_weight_kg": std_w,
    "standard_bmi": std_bmi,
    "standard_skeletal_muscle_kg": std_smm,
    "standard_fat_mass_kg": std_bfm,
    "standard_fat_free_mass_kg": std_ffm,
    "standard_bmr_kcal_per_day": std_bmr,
    "standard_body_fat_percent": 15.0 if male else 23.0,
    "weight_vs_standard_percent": ratio,
    "target_weight_kg": tgt,
    "fat_control_kg": _round_f64(fat_ctrl),
    "muscle_control_kg": _round_f64(mus_ctrl),
    "weight_control_kg": wt_ctrl,
    "body_score": _round_f64(float(score)),
    "body_type_code": _body_type(sex, bmi, body_fat_percent),
    "vendor_thresholds": {
      "bmi": {
        "max": _round_f64(_standard_bmi_upper(bmi_standard)),
        "min": _round_f64(_standard_bmi_lower(bmi_standard)),
      },
      "fat_mass_kg": {"max": _round_f64(fat_hi_m), "min": _round_f64(fat_lo_m)},
      "body_fat_percent": {
        "max": _round_f64(20.0 if male else 28.0),
        "min": _round_f64(10.0 if male else 18.0),
      },
      "weight_kg": {"max": _round_f64(wt_hi), "min": _round_f64(wt_lo)},
      "skeletal_muscle_kg": {"max": _round_f64(smm_hi), "min": _round_f64(smm_lo)},
      "bone_mass_kg": {
        "max": _round_f64(d_hi * 0.067),
        "min": _round_f64(d_lo * 0.067),
      },
      "bmr_kcal_per_day": {"max": bmr_hi, "min": bmr_lo},
      "body_water_mass_kg": {
        "max": _round_f64(d_hi * 0.733),
        "min": _round_f64(d_lo * 0.733),
      },
      "protein_mass_kg": {"max": _round_f64(d_hi * 0.2), "min": _round_f64(d_lo * 0.2)},
      "muscle_mass_kg": {
        "max": _round_f64(d_hi * 0.733 + d_hi * 0.2),
        "min": _round_f64(d_lo * 0.733 + d_lo * 0.2),
      },
    },
  }


# WLA37 ICBodyFatAlgorithmWLA37::calcBF 0x6289c (size 0x35c) and ceil 0x62084.
# Native returns fat MASS kg as binary32 (fcvt s0, d0). Incoming s0 BMI is unused.
# Height is scvtf from the i32 at params+8. Weight is f64 at params+0.
# Impedances: params+0x48 ten f64 in wire order TR,LA,RA,LL,RL at 20 kHz then 100 kHz.
# Caller already applied the 0.826 trunk correction.

# Intercepts assembled at 0x628d0 / 0x628e4 / 0x628f8 (IEEE-754 f64 immediates).
# Tables: .rodata 0x97c30 (low), 0x97d08 (mid), 0x97de0 (high); 27 doubles each.
_CALC_BF_INTERCEPTS = (
  -120.40919720277017,  # d29 < 9
  -62.122012103074155,  # 9 <= d29 < 12
  459.0764926134765,  # d29 >= 12
)

# Coefficient order matches the 0x62ab8..0x62bd4 fmul sequence, not alphabetical.
_CALC_BF_TABLES = (
  (  # 0x97c30, selected when (sum of 20 kHz ohms) / height < 9
    -0.6479385766215462,
    0.0043679913622390884,
    -0.004381009330349479,
    1.4137635273551359,
    0.8972440641334126,
    3.744636921029776e-07,
    1.8622798375611538e-06,
    -3.21667782932078e-06,
    -1.470833592698284e-07,
    2.4410515386819043e-08,
    3659.567683232422,
    6296.513907193069,
    3.183231456205249e-12,
    1.8189894035458565e-12,
    0.0,
    0.0,
    0.0,
    0.0013213006689052598,
    0.0014762989408746378,
    0.0,
    -0.005092671873394028,
    -0.0021319487818419404,
    0.0,
    0.007120547262083763,
    0.003926916457039997,
    -1804.5701659257415,
    -1066.9756438232985,
  ),
  (  # 0x97d08, 9 <= sum20/height < 12
    0.021381666748709484,
    0.001555788203383254,
    -0.001381904887066441,
    0.4323575151173152,
    0.9006858278615505,
    -1.2937164927041833e-05,
    -6.320106709367668e-07,
    -1.2032349709090173e-06,
    -1.0443192763331943e-07,
    -1.385584647017879e-08,
    -64.66867881017569,
    5129.881896858824,
    8.185452315956354e-12,
    -2.2737367544323206e-12,
    0.0,
    0.0,
    0.0,
    0.000754468821800759,
    0.000535878489029979,
    0.0,
    -0.003472532743498761,
    -0.0011707291856231528,
    0.0,
    0.004522027584100812,
    0.0017837707595039292,
    -553.2128575628485,
    -709.2415741807869,
  ),
  (  # 0x97de0, sum20/height >= 12
    -4.523962456566006,
    0.01834022619606135,
    0.011358858326921914,
    -3.7219542380241957,
    0.7795223045250204,
    -3.361591546395537e-06,
    -4.128779710271119e-06,
    1.8855959126110045e-06,
    9.055010410791153e-07,
    2.9024720404891013e-09,
    5488.247822417395,
    1398.7542553591948,
    2.0463630789890885e-12,
    -3.637978807091713e-12,
    0.0,
    0.0,
    0.0,
    0.005983590497858483,
    0.003454020395819304,
    0.0,
    0.0029200088270957703,
    0.0020923325303076647,
    0.0,
    0.0016653107448814724,
    0.0032111340151962605,
    -4140.392727781235,
    446.5100411150056,
  ),
)


def _calc_bf(weight, height, imps):
  # The native routine recomputes BMI; height² and height precede it in the
  # feature vector (d9 is reloaded with height at 0x629a4).
  tr20, la20, ra20, ll20, rl20, tr100, la100, ra100, ll100, rl100 = imps
  h = float(height)
  w = float(weight)
  hundred = 100.0
  parallel20 = tr20 + (la20 * ra20) / (la20 + ra20) + (ll20 * rl20) / (ll20 + rl20)
  parallel100 = (
    tr100 + (la100 * ra100) / (la100 + ra100) + (ll100 * rl100) / (ll100 + rl100)
  )
  total20 = ll20 + ((tr20 + (la20 + ra20)) + rl20)
  total100 = ll100 + ((tr100 + (la100 + ra100)) + rl100)
  w_over_h2 = (w / h) / h
  bmi_f64 = (w_over_h2 * hundred) * hundred
  total20_over_h = total20 / h
  features = (
    w,
    w * w,
    h * h,
    h,
    bmi_f64,
    ra20 - ra100,
    la20 - la100,
    tr20 - tr100,
    rl20 - rl100,
    ll20 - ll100,
    (parallel20 / h) / h,
    (parallel100 / h) / h,
    ra20 / ra100,
    la20 / la100,
    tr20 / tr100,
    ll20 / ll100,
    rl20 / rl100,
    ra20 * bmi_f64,
    la20 * bmi_f64,
    tr20 * bmi_f64,
    rl20 * bmi_f64,
    ll20 * bmi_f64,
    tr100 * bmi_f64,
    rl100 * bmi_f64,
    ll100 * bmi_f64,
    total20_over_h / h,
    (total100 / h) / h,
  )
  # fcmp d29, #9; b.pl mid/high. d29 is sum(20 kHz)/height (0x629d0), not /h^2.
  if total20_over_h < 9.0:
    table = _CALC_BF_TABLES[0]
    intercept = _CALC_BF_INTERCEPTS[0]
  elif total20_over_h < 12.0:
    table = _CALC_BF_TABLES[1]
    intercept = _CALC_BF_INTERCEPTS[1]
  else:
    table = _CALC_BF_TABLES[2]
    intercept = _CALC_BF_INTERCEPTS[2]
  acc = 0.0
  for coeff, feature in zip(table, features):
    acc = acc + coeff * feature
  acc = acc + intercept
  return _f32(acc)


# WLA37 ICBodyFatAlgorithmWLA37::calc (0x62bf8) body.
# Native param sex: 1 = male, 2 = female. Athlete is unused on this path.


def _public_number(value, integer=False):
  if not math.isfinite(value):
    raise ValueError("Vendor calculation returned a non-finite result")
  if integer:
    return int(value)
  return round(value, 2)


def _calculate(weight, profile, imps):
  height = profile.height_cm
  age = profile.age
  sex = 1 if profile.sex == "male" else 2
  bmi_std = BMI_STANDARDS[profile.bmi_standard]
  male = sex == 1

  h2_s = _f32(height * height)
  bmi_raw = (weight * 10000.0) / float(h2_s)
  bmi = float(_round_f32(bmi_raw))

  std_bfm = float(_round_f32(_standard_bfm(height, age, sex, bmi_std)))
  std_ffm = float(_round_f32(_standard_ffm(height, age, sex, bmi_std)))

  height_m2 = float(height * height) / 10000.0

  tr20, la20, ra20, ll20, rl20, tr100, la100, ra100, ll100, rl100 = imps
  if (
    tr20 < 1.0
    or la20 < 100.0
    or ra20 < 100.0
    or ll20 < 100.0
    or rl20 < 100.0
    or tr100 < 1.0
    or la100 < 100.0
    or ra100 < 100.0
    or ll100 < 100.0
    or rl100 < 100.0
  ):
    raise ValueError("Vendor algorithm rejected the measurement (status 2)")

  tr20_c = tr20 * 0.826
  if tr100 > tr20:
    tr100_c = tr20_c - 3.0
  else:
    tr100_c = tr100 * 0.826
  if tr20_c < 0.0 or tr100_c < 0.0:
    raise ValueError("Vendor algorithm rejected the measurement (status 3)")

  imps_c = (
    tr20_c,
    la20,
    ra20,
    ll20,
    rl20,
    tr100_c,
    la100,
    ra100,
    ll100,
    rl100,
  )
  fat_mass_s = _calc_bf(weight, height, imps_c)
  fat_mass_d = float(fat_mass_s)
  fat_pct_d = (fat_mass_d / weight) * 100.0
  if fat_pct_d < 3.0:
    fat_mass_d = weight * 0.03
    fat_pct_d = 3.0
  elif fat_pct_d > 60.0:
    fat_mass_d = weight * 0.6
    fat_pct_d = 60.0
  fat_mass = float(_round_f32(fat_mass_d))
  fat_pct = float(_round_f32(fat_pct_d))

  # Metabolic-age offset from rounded fat percent vs sex tables.
  met_off = 0
  if age >= 10:
    fp = _f32(fat_pct)
    if male:
      if fp < 14.0:
        met_off = -3
      elif fp < 19.0:
        met_off = -2
      elif fp < 24.0:
        met_off = -1
      elif fp < 27.0:
        met_off = 1
      elif fp < 30.0:
        met_off = 2
      elif fp < 33.0:
        met_off = 3
      elif fp < 36.0:
        met_off = 4
      else:
        met_off = 5
    else:
      if fp < 24.0:
        met_off = -3
      elif fp < 28.0:
        met_off = -2
      elif fp < 32.0:
        met_off = -1
      elif fp < 35.0:
        met_off = 1
      elif fp < 38.0:
        met_off = 2
      elif fp < 42.0:
        met_off = 3
      elif fp < 45.0:
        met_off = 4
      elif fp >= 46.0:
        met_off = 5
      else:
        met_off = 0
  metabolic_age = age + met_off

  def _balance(left, right, l20, r20, l100, r100, limit, k=20213.0):
    if abs(right - left) <= limit:
      return left, right
    if right > left:
      delta = (l20 + l100) / k
      if l20 > r20:
        delta = -delta
      return right + delta, right
    delta = (r20 + r100) / k
    if r20 > l20:
      delta = -delta
    return left, left + delta

  def _floor(value, minimum, num, den):
    if value >= minimum:
      return value
    return num / den + minimum

  ra_fat = fat_mass * 0.081201 - ra20 * 0.005752 + ra100 * 0.007476 - 0.662152
  la_fat = fat_mass * 0.081201 - la20 * 0.005752 + la100 * 0.007476 - 0.662152
  rl_fat = fat_mass * 0.135438 - rl20 * 0.00801 + rl100 * 0.008645 + 0.492479
  ll_fat = fat_mass * 0.135438 - ll20 * 0.00801 + ll100 * 0.008645 + 0.492479
  la_fat, ra_fat = _balance(la_fat, ra_fat, la20, ra20, la100, ra100, 0.3)
  ll_fat, rl_fat = _balance(ll_fat, rl_fat, ll20, rl20, ll100, rl100, 0.5)
  tr_fat = fat_mass * 0.552545 + tr20_c * 0.068621 + tr100_c * (-0.131612) + 0.322704
  ra_fat = _floor(ra_fat, 0.1, ra20 + ra100, 20213.0)
  la_fat = _floor(la_fat, 0.1, la20 + la100, 20113.0)
  tr_fat = _floor(tr_fat, 0.1, tr20_c + tr100_c, 20203.0)
  rl_fat = _floor(rl_fat, 0.1, rl20 + rl100, 20213.0)
  ll_fat = _floor(ll_fat, 0.1, ll20 + ll100, 20113.0)

  ffm = weight - fat_mass
  ra_mus = ffm * 0.058707 + ra20 * 0.002847 - ra100 * 0.005857 + 0.561911
  la_mus = ffm * 0.058707 + la20 * 0.002847 - la100 * 0.005857 + 0.561911
  tr_mus = ffm * 0.440922 + tr20_c * 0.005246 + tr100_c * (-0.010469) - 0.275461
  rl_mus = ffm * 0.176554 - rl20 * 0.007381 + rl100 * 0.008157 - 0.688932
  ll_mus = ffm * 0.176554 - ll20 * 0.007381 + ll100 * 0.008157 - 0.688932
  ra_mus = _floor(ra_mus, 0.2, ra20 + ra100, 20213.0)
  la_mus = _floor(la_mus, 0.2, la20 + la100, 20113.0)
  tr_mus = _floor(tr_mus, 0.7, tr20_c + tr100_c, 20203.0)
  rl_mus = _floor(rl_mus, 0.2, rl20 + rl100, 20213.0)
  ll_mus = _floor(ll_mus, 0.2, ll20 + ll100, 20113.0)

  water = ffm * 0.733
  protein = ffm * 0.2
  muscle = water + protein
  smm = water * 0.834 - 2.627
  bone = ffm * 0.067
  bmr = int(ffm * 21.6 + 370.0)
  sub_fat = (fat_pct * (-0.0002) + 0.72) * fat_pct
  wat_pct = water / weight * 100.0
  prot_pct = protein / weight * 100.0
  mus_pct = muscle / weight * 100.0
  smm_pct = smm / weight * 100.0

  visc_i = int(fat_mass * 0.502 + ffm * (-0.029) - 0.477)
  visc_i = min(20, visc_i)
  visc_i = max(1, visc_i)

  h_d = float(height)
  smi = (la_mus + ra_mus + ll_mus + rl_mus) / height_m2
  den_arm_fat = std_bfm * 0.101 + h_d * (-0.004) + 0.331
  den_leg_fat = std_bfm * 0.215 + h_d * (-0.005) + 0.391
  den_tr_fat = h_d * 0.006 + std_bfm * 0.389 - 0.683
  den_arm_mus = std_ffm * 0.102 + h_d * (-0.045) + weight * 0.02 + 3.752
  den_leg_mus = std_ffm * 0.168 + h_d * (-0.056) + weight * 0.059 + 4.775
  den_tr_mus = std_ffm * 0.485 + h_d * (-0.16) + weight * 0.166 + 13.595
  scale = 100.0
  la_fat_vs = la_fat / den_arm_fat * scale
  ra_fat_vs = ra_fat / den_arm_fat * scale
  ll_fat_vs = ll_fat / den_leg_fat * scale
  rl_fat_vs = rl_fat / den_leg_fat * scale
  tr_fat_vs = tr_fat / den_tr_fat * scale
  la_mus_vs = la_mus / den_arm_mus * scale
  ra_mus_vs = ra_mus / den_arm_mus * scale
  ll_mus_vs = ll_mus / den_leg_mus * scale
  rl_mus_vs = rl_mus / den_leg_mus * scale
  tr_mus_vs = tr_mus / den_tr_mus * scale

  whr = float(_waist_hip_ratio(weight, height, _f32(bmi), imps_c))
  result = _postprocess(height, sex, age, bmi_std, weight, bmi, fat_pct)
  result["bmi"] = bmi
  result["body_fat_percent"] = fat_pct
  result["muscle_percent"] = _round_f32(mus_pct)
  result["subcutaneous_fat_percent"] = _round_f32(sub_fat)
  result["visceral_fat_index"] = _round_f32(float(visc_i))
  result["bone_mass_kg"] = _round_f32(bone)
  result["body_water_percent"] = _round_f32(wat_pct)
  result["protein_percent"] = _round_f32(prot_pct)
  result["skeletal_muscle_percent"] = _round_f32(smm_pct)
  result["bmr_kcal_per_day"] = bmr
  result["metabolic_age_years"] = metabolic_age
  result["skeletal_muscle_index_kg_m2"] = _round_f32(smi)
  result["waist_hip_ratio"] = whr
  result["segments"] = {
    "left_arm": {
      "fat_mass_kg": la_fat,
      "fat_vs_standard_percent": la_fat_vs,
      "muscle_mass_kg": la_mus,
      "muscle_vs_standard_percent": la_mus_vs,
    },
    "left_leg": {
      "fat_mass_kg": ll_fat,
      "fat_vs_standard_percent": ll_fat_vs,
      "muscle_mass_kg": ll_mus,
      "muscle_vs_standard_percent": ll_mus_vs,
    },
    "right_arm": {
      "fat_mass_kg": ra_fat,
      "fat_vs_standard_percent": ra_fat_vs,
      "muscle_mass_kg": ra_mus,
      "muscle_vs_standard_percent": ra_mus_vs,
    },
    "right_leg": {
      "fat_mass_kg": rl_fat,
      "fat_vs_standard_percent": rl_fat_vs,
      "muscle_mass_kg": rl_mus,
      "muscle_vs_standard_percent": rl_mus_vs,
    },
    "trunk": {
      "fat_mass_kg": tr_fat,
      "fat_vs_standard_percent": tr_fat_vs,
      "muscle_mass_kg": tr_mus,
      "muscle_vs_standard_percent": tr_mus_vs,
    },
  }

  for name, pct_key in (
    ("body_water_mass_kg", "body_water_percent"),
    ("fat_mass_kg", "body_fat_percent"),
    ("muscle_mass_kg", "muscle_percent"),
    ("protein_mass_kg", "protein_percent"),
    ("skeletal_muscle_mass_kg", "skeletal_muscle_percent"),
  ):
    result[name] = _public_number(weight * result[pct_key] / 100.0)
  result["fat_free_mass_kg"] = _public_number(
    weight * (1.0 - result["body_fat_percent"] / 100.0)
  )
  # Derived masses use the native one-decimal values, before public rounding.
  # Round in place so the consumer dictionary and its nested shapes exist once.
  for key, value in result.items():
    if isinstance(value, dict):
      for fields in value.values():
        for field, number in fields.items():
          fields[field] = _public_number(number, integer=isinstance(number, int))
    else:
      result[key] = _public_number(value, integer=isinstance(value, int))
  return result


class BodyComposition:
  def calculate(self, measurement: dict, profile: Profile) -> dict:
    impedance_channels(measurement)
    weight = measurement["weight_kg"]
    if not math.isfinite(weight) or not 20 <= weight <= 200:
      raise ValueError("WLA37 requires weight between 20 and 200 kg")
    try:
      return _calculate(weight, profile, measurement["impedance_values"])
    except ArithmeticError as error:
      # IEEE overflow/division by zero represents a non-finite computed field.
      raise ValueError("Vendor calculation returned a non-finite result") from error
