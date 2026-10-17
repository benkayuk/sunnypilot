import unittest
from types import SimpleNamespace
from unittest.mock import Mock, mock_open, patch

from openpilot.selfdrive.car.secoc import configure_secoc_key

KEY = bytes(range(16))  # synthetic, never a vehicle key


class TestSecocStartup(unittest.TestCase):
  def setUp(self):
    self.CI = SimpleNamespace(CP=SimpleNamespace(brand='fisker', passive=False, secOcKeyAvailable=False),
                              CS=SimpleNamespace(secoc_key=None), CC=SimpleNamespace(secoc_key=None))
    self.params = Mock()
    self.params.get.return_value = None
    self.recv, self.send = Mock(), Mock()

  def configure(self, recovered=None, cached='', replay=False, controller_available=True):
    with patch('openpilot.selfdrive.car.secoc.open', mock_open(read_data=cached)), \
         patch('openpilot.selfdrive.car.secoc.recover_secoc_key', return_value=recovered) as recover:
      configure_secoc_key(self.CI, self.params, self.recv, self.send, controller_available=controller_available, replay=replay)
    return recover

  def test_recovered_key_available_and_persisted(self):
    recover = self.configure(recovered=KEY)
    recover.assert_called_once_with(self.recv, self.send)
    self.assertTrue(self.CI.CP.secOcKeyAvailable)
    self.assertEqual(self.CI.CS.secoc_key, KEY)
    self.assertEqual(self.CI.CC.secoc_key, KEY)
    self.params.put.assert_called_once_with('SecOCKey', KEY.hex(), block=True)

  def test_saved_key_skips_diagnostics(self):
    self.params.get.return_value = KEY.hex()
    self.configure().assert_not_called()
    self.assertTrue(self.CI.CP.secOcKeyAvailable)

  def test_cache_fallback_and_invalid_hex(self):
    self.params.get.return_value = 'z' * 32
    self.configure(cached=KEY.hex()).assert_not_called()
    self.assertTrue(self.CI.CP.secOcKeyAvailable)

  def test_failure_and_malformed_keys_remain_blocked(self):
    for stored in (None, 'z' * 32, '01', KEY.hex() + '00'):
      with self.subTest(stored=stored):
        self.params.get.return_value = stored
        self.configure(cached='invalid')
        self.assertFalse(self.CI.CP.secOcKeyAvailable)
        self.assertIsNone(self.CI.CC.secoc_key)
        self.params.put.assert_not_called()

  def test_no_diagnostics_for_passive_replay_or_other_brand(self):
    self.configure(replay=True).assert_not_called()
    self.CI.CP.passive = True
    self.configure().assert_not_called()
    self.CI.CP.passive = False
    self.CI.CP.brand = 'toyota'
    self.configure().assert_not_called()

  def test_saved_key_without_controller(self):
    self.CI.CC = None
    self.params.get.return_value = KEY.hex()
    self.configure(controller_available=False).assert_not_called()
    self.assertTrue(self.CI.CP.secOcKeyAvailable)


if __name__ == '__main__':
  unittest.main()
