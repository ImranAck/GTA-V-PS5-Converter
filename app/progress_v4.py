"""Transparent, stage-based progress for the upstream 18-step pipeline.
No bogus smooth interpolation: progress remains fixed during an unfinished stage.
"""
import re

# Stage start is the % completed by *previous* stages, not a promise of remaining time.
_COMPLETED_BEFORE = [0,1,8,12,22,27,54,60,65,71,76,83,93,94,95,96,97,99]
_LABELS = {
 1:'Preparando plantillas', 2:'Importando modelo', 3:'Analizando materiales',
 4:'Reparando recursos', 5:'Verificando materiales',6:'Convirtiendo geometría',
 7:'Separando mallas',8:'Preparando LOD',9:'Separando modelo HD',
 10:'Preparando LOD HD',11:'Reparando colisiones',12:'Convirtiendo texturas',
 13:'Preparando físicas',14:'Preparando asientos y layouts',15:'Importando etiquetas',
 16:'Preparando personalización',17:'Construyendo paquete',18:'Validando paquete'
}
STEP = re.compile(r'^\[(\d{2,})\]\s+(.+)$')

class StageProgress:
    def __init__(self, publish, expected_steps=None):
        self.publish=publish
        self.expected_steps=expected_steps
        self.current=0
        self.percent=0
        self.batch_count=0
        self.batch_done=0
    def line(self, msg):
        msg=msg.lstrip()
        batch=re.match(r'^PERF_TUNING_BATCH .*?count=(\d+)',msg)
        if batch:
            self.batch_count=int(batch.group(1))
            self.batch_done=0
            return
        if msg.startswith('TUNING_PART_OK ') and self.batch_count:
            self.batch_done=min(self.batch_count,self.batch_done+1)
            if self.expected_steps:
                estimate=min(95,int((self.current-1+self.batch_done/self.batch_count)*95/max(self.expected_steps,self.current)))
                self.percent=max(self.percent,estimate)
            self.publish(self.percent,f'Tuning: {self.batch_done}/{self.batch_count} piezas procesadas')
            return
        m=STEP.match(msg)
        if not m:
            return
        step=int(m.group(1))
        if step < 1:return
        self.current=step
        self.batch_count=0
        self.batch_done=0
        label=m.group(2)
        # The pipeline adds stages during repairs; show an expressly estimated
        # percentage, with the actual stage count. Only validated success is 100%.
        if self.expected_steps:
            estimate = min(95, int((step-1)*95/max(self.expected_steps,step)))
            if label == 'validate target pack': estimate = 99
        else:
            estimate = _COMPLETED_BEFORE[min(step,18)-1]
        self.percent=max(self.percent,estimate)
        self.publish(self.percent, f'{label} · etapa {step} (estimación)')
    def complete(self):
        self.percent=100
        self.publish(100,'Conversión y validación completadas')


def ftp_percent(sent,total):
    return min(99,round(sent*99/max(total,1)))
