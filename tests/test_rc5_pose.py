"""Reject unsafe skeleton rewrites; permit bounded single-root tuning repair."""
import copy
import struct
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'motor/tools'))
from repair_pc_pose_precision import repair_single_root_translation, repair_matrix, SYSTEM_BASE

class RC5PoseTests(unittest.TestCase):
    def setUp(self):
        self.identity=[1.,0.,0.,0.,0.,1.,0.,0.,0.,0.,1.,0.,0.,0.,0.,1.]
        old=self.identity[:]; old[13]=1.04;old[14]=-.596;old[15]=0.
        self.raw=bytearray(struct.pack('<16f',*old)+b'other source bytes')
        self.skeleton={'bones':[{}],'parents':[-1],'header':{'TransformationsInvertedPointer':SYSTEM_BASE}}
        self.pose={'rejections':[{'boneIndex':0}], 'bones':[{'name':'root','globalPose':self.identity,'localComparison':{'mismatches':[]},'inverseBindTimesGlobalComparison':{'mismatches':[{'field':'M42'},{'field':'M43'}]}}]}
        self.skin={'geometries':[{'streams':[{'vertexVisits':10,'rigidBoneVertices':[{'boneIndex':0,'vertices':10}]}]}]}
    def repair(self):return repair_single_root_translation(self.raw,self.skeleton,self.pose,self.skin)
    def test_translation_only(self):
        old=bytes(self.raw); result=self.repair()
        self.assertEqual(struct.unpack_from('<3f',self.raw,48),(0.,0.,0.))
        self.assertEqual(self.raw[:48],old[:48]);self.assertEqual(self.raw[60:],old[60:])
        self.assertEqual(result['mode'],'single-root-inverse-translation')
    def test_multibone_rejected_without_write(self):
        self.skeleton['bones'].append({}); self.skeleton['parents'].append(0); old=bytes(self.raw)
        with self.assertRaises(SystemExit):self.repair()
        self.assertEqual(self.raw,old)
    def test_rotation_rejected(self):
        self.pose['bones'][0]['inverseBindTimesGlobalComparison']['mismatches'].append({'field':'M11'})
        with self.assertRaises(SystemExit):self.repair()
    def test_local_mismatch_rejected(self):
        self.pose['bones'][0]['localComparison']['mismatches']=[{'field':'M41'}]
        with self.assertRaises(SystemExit):self.repair()
    def test_unverified_skin_rejected(self):
        self.skin['geometries'][0]['streams'][0]['rigidBoneVertices'][0]['vertices']=9
        with self.assertRaises(SystemExit):self.repair()
    def test_original_precision_limit_unchanged(self):
        old=bytes(self.raw)
        with self.assertRaisesRegex(SystemExit,'not a precision error'):repair_matrix(self.raw,0,self.identity,'base')
        self.assertEqual(self.raw,old)
    def test_source_launcher_uses_build_venv(self):
        source=(ROOT/'START-CONVERTER.bat').read_text(encoding='utf-8')
        self.assertIn('from PIL import Image, ImageTk',source)
        self.assertIn('".venv-build\\Scripts\\python.exe" launch.py', source)

if __name__=='__main__': unittest.main()
