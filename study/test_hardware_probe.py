import copy
import unittest

from hardware_probe import validate


class HardwareGateTests(unittest.TestCase):
    def setUp(self):
        self.record = {
            "devices": [{"name": "NVIDIA H100 80GB HBM3", "memory_mib": 81559,
                         "uuid": "GPU-fixture", "driver_version": "fixture",
                         "mig_mode": "Disabled"}],
            "runtime": {"torch_device_count": 1, "torch_device_name": "NVIDIA H100 80GB HBM3",
                        "cuda": "fixture", "torch": "fixture"},
            "cuda_smoke_passed": True,
        }

    def test_complete_matching_evidence_passes(self):
        validate(self.record)

    def test_catalog_only_or_missing_evidence_fails(self):
        for record in ({}, {"gpu": "H100"}, {"devices": self.record["devices"]}):
            with self.assertRaises(ValueError):
                validate(record)

    def test_wrong_device_or_partition_fails(self):
        for patch in ({"name": "NVIDIA A100"}, {"mig_mode": "Enabled"},
                      {"mig_mode": "N/A"}, {"memory_mib": 40960}, {"uuid": ""}):
            record = copy.deepcopy(self.record)
            record["devices"][0].update(patch)
            with self.assertRaises(ValueError):
                validate(record)

    def test_wrong_count_or_cuda_failure_fails(self):
        for field, value in (("torch_device_count", 2), ("torch_device_name", "Other"),
                             ("cuda", None)):
            record = copy.deepcopy(self.record)
            record["runtime"][field] = value
            with self.assertRaises(ValueError):
                validate(record)
        self.record["cuda_smoke_passed"] = False
        with self.assertRaises(ValueError):
            validate(self.record)


if __name__ == "__main__":
    unittest.main()
