import os,unittest
from pathlib import Path
from unittest.mock import patch
from sefang.config import Config
class SefangConfigTests(unittest.TestCase):
 def test_legacy_configuration_paths_and_channels_unchanged(self):
  with patch.dict(os.environ,{'SE_DATA_ROOT':'/tmp/legacy-data','SE_STATE_ROOT':'/tmp/legacy-side','SE_CHANNEL_IDS':'123,456','SE_OFFLINE':'1'},clear=True):
   c=Config.environment();self.assertEqual(c.data,Path('/tmp/legacy-data'));self.assertEqual(c.state,Path('/tmp/legacy-side'));self.assertEqual(c.channels,(123,456));self.assertTrue(c.offline)
 def test_new_prefix_wins_explicitly_without_changing_path_schema(self):
  with patch.dict(os.environ,{'SE_DATA_ROOT':'/tmp/old','SE_STATE_ROOT':'/tmp/old','SE_CHANNEL_IDS':'999','SE_OFFLINE':'1','SEFANG_DATA_ROOT':'/tmp/data','SEFANG_STATE_ROOT':'/tmp/side','SEFANG_CHANNEL_IDS':'123','SEFANG_OFFLINE':'0'},clear=True):
   c=Config.environment();self.assertEqual(c.channels,(123,));self.assertEqual(c.db,Path('/tmp/data/database/telegram/index.db'));self.assertEqual(c.secrets_root,Path('/tmp/data/secrets'));self.assertFalse(c.offline)
