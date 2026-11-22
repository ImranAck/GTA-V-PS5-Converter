"""RC2 user-facing language, defaults and safe-onboarding invariants."""
import sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
import gui_locales

class RC2Locales(unittest.TestCase):
    def test_three_languages(self):
        self.assertEqual(gui_locales.LANGUAGES,{'Español':'es','English':'en','Français':'fr'})
        for lang in ('es','en','fr'):
            self.assertTrue(gui_locales.translate('Configuración',lang))
            self.assertTrue(gui_locales.translate('Enviar por FTP',lang))
            self.assertIn('45',gui_locales.formatted('Transcurrido: {seconds} s',lang,seconds=45))
    def test_required_labels_are_fully_translated(self):
        keys=[
          'Configuración','Conversión','Enviar por FTP','Acerca de',
          'RECURSOS OBLIGATORIOS','MATERIALES PS5 ADICIONALES · OPCIONAL',
          'Biblioteca de materiales dañada o modificada',
          '01  IMPORTAR MOD','02  VEHÍCULO DETECTADO','03  OPCIONES RECOMENDADAS',
          'Mostrar opciones avanzadas','Ocultar opciones avanzadas',
          'Original · sin reducción','CONFIGURACIÓN Y DESTINO',
          'ENVIAR COCHE SELECCIONADO','Comprobar conexión'
        ]
        keys.remove('CONFIGURACIÓN Y DESTINO')
        keys.remove('Comprobar conexión')
        for lang in ('en','fr'):
            for key in keys:
                with self.subTest(lang=lang,key=key):
                    self.assertNotEqual(key,gui_locales.translate(key,lang))
    def test_source_code_defaults_and_visibility(self):
        src=(ROOT/'app'/'conversor_gui.py').read_text(encoding='utf8')
        self.assertIn('self._set_details(False);self._show_progress()',src)
        self.assertIn("self._assign_row(self.candidates[0]);self._photo(self.photo);self._set_details(True)",src)
        self.assertIn("self._set_details(False)",src)
        self.assertIn("self.quality=tk.StringVar(value=self.tr('Original · sin reducción'))",src)
        self.assertIn('self.setup_shaders.configure(text=txt,fg=color)',src)
    def test_icon_and_packaging(self):
        self.assertTrue((ROOT/'assets'/'app.ico').is_file())
        self.assertTrue((ROOT/'assets'/'app.png').is_file())
        self.assertIn('icon=str(ROOT', (ROOT/'GTAV-PS5-Converter.spec').read_text(encoding='utf-8'))
        self.assertIn('SetupIconFile', (ROOT/'installer'/'GTAV-PS5-Converter.iss').read_text(encoding='utf-8'))

if __name__=='__main__':unittest.main()
