"""No private GTA V resources required: resumable-steps regression suite."""
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE=Path(__file__).resolve().parents[1]/'motor'/'tools'/'convert_vehicle.py'
spec=importlib.util.spec_from_file_location('test_convert_vehicle_speed', MODULE)
converter=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=converter
spec.loader.exec_module(converter)

class ResumeSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name)
        self.work=self.base/'build'; self.work.mkdir()
        self.checkpoints=self.work/'checkpoints.json'
        self.script=self.base/'work.py'
        self.script.write_text('''
import pathlib,sys
out=pathlib.Path(sys.argv[sys.argv.index('--output')+1]);out.parent.mkdir(parents=True,exist_ok=True)
count=pathlib.Path(sys.argv[sys.argv.index('--count')+1]);n=int(count.read_text())+1 if count.exists() else 1
count.write_text(str(n))
out.write_text('run:'+str(n))
if '--fail' in sys.argv:sys.exit(2)
''',encoding='utf-8')
        self.env=patch.dict(os.environ, {'GTAV_HOST_BUILD_DIR':str(self.work)})
        self.env.start();self.addCleanup(self.env.stop)

    def cmd(self,name,fail=False):
        args=[sys.executable,str(self.script),'--output',str(self.work/name), '--count',str(self.base/(name+'.count'))]
        return args+(['--fail'] if fail else [])

    def test_repeated_valid_result_skipped(self):
        cmd=self.cmd('first.out')
        converter.Plan(False,resume_file=self.checkpoints).run('import',cmd)
        converter.Plan(False,resume_file=self.checkpoints).run('import',cmd)
        self.assertEqual((self.base/'first.out.count').read_text(),'1')

    def test_mutated_output_forces_recompute(self):
        cmd=self.cmd('first.out')
        converter.Plan(False,resume_file=self.checkpoints).run('import',cmd)
        (self.work/'first.out').write_text('corrupted')
        converter.Plan(False,resume_file=self.checkpoints).run('import',cmd)
        self.assertEqual((self.base/'first.out.count').read_text(),'2')

    def test_failed_outputs_are_never_reused(self):
        cmd=self.cmd('broken.out',fail=True)
        with self.assertRaises(converter.ConvertError):
            converter.Plan(False,resume_file=self.checkpoints).run('import',cmd)
        converter.Plan(False,resume_file=self.checkpoints).run('import',self.cmd('broken.out'))
        self.assertEqual((self.base/'broken.out.count').read_text(),'2')

    def test_two_earlier_steps_skipped_after_later_failure(self):
        first=self.cmd('first.out'); second=self.cmd('second.out'); last=self.cmd('last.out',fail=True)
        plan=converter.Plan(False,resume_file=self.checkpoints)
        plan.run('import',first); plan.run('report',second)
        with self.assertRaises(converter.ConvertError):plan.run('repair',last)
        again=converter.Plan(False,resume_file=self.checkpoints)
        again.run('import',first);again.run('report',second)
        self.assertEqual((self.base/'first.out.count').read_text(),'1')
        self.assertEqual((self.base/'second.out.count').read_text(),'1')
        again.run('repair',self.cmd('last.out'))
        self.assertEqual((self.base/'last.out.count').read_text(),'2')

    def test_command_change_invalidates_following_cache(self):
        first=self.cmd('first.out');second=self.cmd('second.out')
        p=converter.Plan(False,resume_file=self.checkpoints);p.run('import',first);p.run('report',second)
        changed=self.cmd('first.out') + ['--different-flag']
        p=converter.Plan(False,resume_file=self.checkpoints);p.run('import',changed);p.run('report',second)
        self.assertEqual((self.base/'first.out.count').read_text(),'2')
        self.assertEqual((self.base/'second.out.count').read_text(),'2')

    def test_no_resume_keeps_normal_execution(self):
        cmd=self.cmd('first.out')
        converter.Plan(False).run('import',cmd)
        converter.Plan(False).run('import',cmd)
        self.assertEqual((self.base/'first.out.count').read_text(),'2')

if __name__=='__main__':unittest.main()
