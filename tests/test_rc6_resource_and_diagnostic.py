"""General regression: flat resource ownership and directed repair diagnostics."""
import sys
import unittest
import tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'motor/tools'))
import native_vehicle_resource as writer
from native_resource_builder import ObjectArena
from gtavmenu_tools import vehicle_contracts, asset_formats
from convert_vehicle import ConvertError, refusal, clear_resumed_pack_inputs

class ResourceAndDiagnosis(unittest.TestCase):
    def test_flat_resources_with_pointer_targets(self):
        c=vehicle_contracts.load(); pc,native=c['pc']['resource'],c['native']['resource']
        for size in (16, 128, 8192, 65536):
            with self.subTest(size=size):
                arena=ObjectArena(); arena.add('root',bytes(pc['root']['bytes']))
                target=arena.add('object',bytes([123])*size)
                slot=native['info']['rootPointerOffset']; arena.pointer(slot,None)
                arena.pointer(0 if slot!=0 else 8,target)
                blob,g=arena.render(native['rootPlacement']['sourceBase'])
                g.update(fragment={'rootOffset':0,'pageInfoPointerOffset':slot,'targets':{}},externalTextureLinks=[])
                envelope,graph=writer.build(blob,g,pc,native)
                _,report=writer.readback(envelope,graph,native)
                self.assertTrue(report['componentPreimageRecovered'])
    def test_directed_repair_uses_original_reason(self):
        reason='triangle-declaration-unqualified'
        log=f'physics-child mesh topology has rejected geometry ({reason})\n'
        msg=refusal(8,'convert',[log],found={'triangle-counts':[]},auto=True)
        self.assertNotIn(reason,msg)
        exc=ConvertError(msg,tool_output=log)
        self.assertTrue(exc.has_tool_reason(reason))
        self.assertFalse(exc.has_tool_reason('not a precision error'))
    def test_resume_cleans_only_private_pack_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            work=Path(tmp)/'work'; work.mkdir(); stage=work/'pack-inputs'; stage.mkdir()
            (stage/'old.pft').write_bytes(b'old'); (work/'source').write_bytes(b'keep')
            clear_resumed_pack_inputs(work)
            self.assertFalse(stage.exists()); self.assertEqual((work/'source').read_bytes(),b'keep')
            clear_resumed_pack_inputs(work)
    def test_other_errors_remain_strict(self):
        self.assertFalse(ConvertError('unknown shader').has_tool_reason('triangle-declaration-unqualified'))

if __name__=='__main__': unittest.main()
