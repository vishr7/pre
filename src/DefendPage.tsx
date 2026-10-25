import type { Cell, ProjectFile } from './api';
import DefendVoice from './DefendVoice';

export default function DefendPage({ base, files, cells }: { base: string; files: ProjectFile[]; cells: Cell[] }) {
  return (
    <div className="research-desk defend-workspace">
      <div className="tool-eyebrow">PRE DEFEND</div>
      <h2>Defend</h2>
      <p className="research-lead">Ask challenging thesis defense questions about our assumptions, methodology, and findings.</p>
      <DefendVoice base={base} files={files} cells={cells} />
    </div>
  );
}
