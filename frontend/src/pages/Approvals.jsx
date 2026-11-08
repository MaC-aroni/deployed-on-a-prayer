import { useState } from "react";
import NodeDrawer from "../components/NodeDrawer.jsx";
import { NOW, STEP_BY_ID } from "../data/mock.js";
import { ApprovalList } from "./Migration.jsx";

export default function Approvals() {
  const [selected, setSelected] = useState(null);
  return (
    <>
      <div className="page-head">
        <h1>Approvals</h1>
        <p className="muted">Raised by the Compliance agent as Jira tickets. Humans approve; agents never do.</p>
      </div>
      <ApprovalList t={NOW} onOpen={setSelected} />
      {selected && <NodeDrawer step={STEP_BY_ID[selected]} t={NOW} onClose={() => setSelected(null)} />}
    </>
  );
}
