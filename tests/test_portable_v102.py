"""Standalone bundle, language and scroll regression checks (no display needed)."""
from __future__ import annotations
import ast
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
import gui_locales
from conversor_gui import ConverterUI
import conversor_v2_core

class FakeWidget:
    def __init__(self,parent=None,scroll=False):
        self.master=parent
        self._gtav_page_scroll=scroll
        self.steps=[]
    def yview_scroll(self,steps,units):self.steps.append((steps,units))

class WheelAndLocalesTests(unittest.TestCase):
    def setUp(self):self.ui=ConverterUI.__new__(ConverterUI)

    def test_wheel_cannot_change_value_and_scrolls_page(self):
        canvas=FakeWidget(scroll=True)
        combo=FakeWidget(parent=FakeWidget(parent=canvas))
        self.assertEqual(self.ui._wheel_over_value(types.SimpleNamespace(widget=combo,delta=-120)), 'break')
        self.assertEqual(canvas.steps,[(1,'units')])
        self.assertEqual(self.ui._wheel_over_value(types.SimpleNamespace(widget=combo,delta=120)), 'break')
        self.assertEqual(canvas.steps[-1],(-1,'units'))

    def test_x11_and_touchpad_deltas(self):
        canvas=FakeWidget(scroll=True)
        ev=types.SimpleNamespace(widget=FakeWidget(parent=canvas),num=5,delta=0)
        self.assertEqual(self.ui._wheel_over_value(ev),'break')
        self.assertEqual(canvas.steps,[(1,'units')])
        self.assertEqual(self.ui._wheel_steps(types.SimpleNamespace(delta=-1)),1)
        self.assertEqual(self.ui._wheel_steps(types.SimpleNamespace(delta=0)),0)

    def test_value_controls_outside_scroll_area_remain_unchanged(self):
        combo=FakeWidget()
        self.assertEqual(self.ui._wheel_over_value(types.SimpleNamespace(widget=combo,delta=-120)), 'break')
        self.assertEqual(combo.steps,[])

    def test_french_ui_terms_and_partial_warning(self):
        for key in ('Importar referencia de sonido o llantas…',
                    'recursos originales PS5 + vehiclelayouts.meta',
                    'Conversión completada con piezas omitidas',
                    'El coche principal se ha convertido y el ZIP se ha validado en PC.\nLos siguientes elementos opcionales NO están incluidos en esta conversión:',
                    'Indexando materiales PS5…'):
            self.assertNotEqual(gui_locales.translate(key,'fr'),key)
        self.assertIn('personnalisation',gui_locales.translate('Conversión completada con piezas omitidas','fr') + ' ' + gui_locales.translate('Consulta AVISO-CONVERSION-PARCIAL.txt dentro del ZIP. Comprueba luces, manejo y modificaciones en PS5 antes de compartirlo.','fr'))

    def test_last_compatibility_panel_is_removed_and_languages_remain(self):
        src=(ROOT/'app'/'conversor_gui.py').read_text(encoding='utf8')
        self.assertNotIn("self.label(f,'COMPATIBILIDAD Y DESTINO'",src)
        self.assertIn("('conversion','Conversión'",src)
        self.assertIn("self._install_wheel_controls()",src)
        self.assertNotIn("unbind_all('<MouseWheel>')",src)

    def test_frozen_resource_roots_use_meipass(self):
        self.assertIn("getattr(sys, '_MEIPASS'",(ROOT/'app'/'v3_engine.py').read_text(encoding='utf8'))
        self.assertIn("getattr(sys, '_MEIPASS'",(ROOT/'app'/'conversor_v2_core.py').read_text(encoding='utf8'))
        self.assertIn("icon=engine.ROOT/",(ROOT/'app'/'conversor_gui.py').read_text(encoding='utf8'))

    def test_singlefile_bundle_spec_and_game_files_excluded(self):
        text=(ROOT/'GTAV-PS5-Converter.spec').read_text(encoding='utf8')
        self.assertIn('analysis.binaries,',text)
        self.assertIn('analysis.datas,',text)
        self.assertNotIn('coll = COLLECT(',text)
        self.assertIn("'tools/7zip'",text)
        self.assertIn('dist\\GTAV-PS5-Converter.exe',(ROOT/'CREAR-EXE.bat').read_text(encoding='utf8'))
        for base in ('app','motor'):
            found=[p for p in (ROOT/base).rglob('*') if p.is_file() and p.suffix.lower() in ('.pft','.pdr','.ptd','.awc','.rel')]
            self.assertEqual(found,[])

    def test_progress_is_localized_without_changing_engine_logging(self):
        self.ui.language='fr'
        self.assertIn('Étape 4',self.ui._localize_progress('repair auto · etapa 4 (estimación)'))
        self.assertIn('Correction du modèle',self.ui._localize_progress('repair auto · etapa 4 (estimación)'))
        self.assertIn('Traitement des fichiers du véhicule',self.ui._localize_progress('unknown phase · etapa 19 (estimación)'))
        self.assertIn('Pièces de personnalisation : 3/35',self.ui._localize_progress('Tuning: 3/35 piezas procesadas'))

    def test_source_7zip_locator_can_find_embedded_binary(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            folder=root/'tools'/'7zip';folder.mkdir(parents=True)
            (folder/'7z.exe').touch();(folder/'7z.dll').touch()
            with patch.object(conversor_v2_core,'ROOT',root):
                self.assertEqual(conversor_v2_core.find_7z(),str(folder/'7z.exe'))

if __name__ == '__main__':unittest.main()
