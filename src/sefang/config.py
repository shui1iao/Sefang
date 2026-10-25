from dataclasses import dataclass
from pathlib import Path
import os

@dataclass(frozen=True)
class Config:
 data:Path
 state:Path
 channels:tuple[int,...]
 offline:bool=False
 static:Path=Path(__file__).resolve().parent/'static'
 @property
 def db(self):return self.data/'database/telegram/index.db'
 @property
 def db_path(self):return self.data/'database/ledger.db'
 @property
 def secrets_root(self):return self.data/'secrets'
 @property
 def candidate_root(self):return self.data/'generated'
 @property
 def tools_root(self):return self.data/'tools'
 @property
 def covers(self):return self.candidate_root/'telegram-catalog/covers'
 @classmethod
 def environment(cls):
  # Existing installations retain SE_* without rewriting private configuration.
  def setting(name):
   current='SEFANG_'+name
   return os.environ[current] if current in os.environ else os.environ['SE_'+name]
  data=Path(setting('DATA_ROOT')).resolve();state=Path(setting('STATE_ROOT')).resolve()
  channels=tuple(int(v) for v in setting('CHANNEL_IDS').split(','))
  if not channels or len(channels)>100 or any(v<=0 for v in channels):raise ValueError('invalid local allowlist')
  return cls(data,state,channels,os.environ.get('SEFANG_OFFLINE',os.environ.get('SE_OFFLINE'))=='1')
