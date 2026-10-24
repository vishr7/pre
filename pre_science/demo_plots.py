"""Fixed trusted developer demo: python -m pre_science.demo_plots.

Never reuse the local executor below for user-submitted or AI-generated code.
"""

import hashlib
import json

from .experiment import ExperimentService
from .plots import ArtifactStore
from .schemas import ExperimentRequest
from .worker import run_worker


def main():
    store = ArtifactStore()

    class TrustedDemoExecutor:
        def execute(self, request):
            return run_worker(request, artifact_store=store)

    result = ExperimentService(TrustedDemoExecutor()).run(ExperimentRequest(
        experiment_id='sine-wave-demo', random_seed=42, code='''
import numpy as np
import matplotlib.pyplot as plt
x = np.linspace(0, 10, 100)
y = np.sin(x)
plt.figure(figsize=(6.4, 4.8))
plt.plot(x, y)
plt.title("Sine Wave Experiment")
plt.xlabel("X")
plt.ylabel("sin(x)")
plt.show()
report_metric("mean_y", float(np.mean(y)))
print("Mean y:", float(np.mean(y)))
'''))
    if result.status != 'success' or len(result.artifacts) != 1:
        raise RuntimeError(result.model_dump_json())
    artifact = result.artifacts[0]
    png = store.retrieve(artifact.artifact_id)
    if hashlib.sha256(png).hexdigest() != artifact.sha256:
        raise RuntimeError('Retrieved artifact checksum mismatch')
    print(json.dumps({'result': result.model_dump(mode='json'),
                      'retrieved_png_bytes': len(png), 'checksum_verified': True}, indent=2))
    # Intentionally retain the file for inspection and later backend handoff.


if __name__ == '__main__':
    main()
