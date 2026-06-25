# Author: Stian Skogbrott
# License: Apache-2.0
"""Add TEE Audit Protocol section to paper (tex and md).

TEE = Trusted Execution Environment (AMD SEV-SNP / Intel SGX / NVIDIA HCC).
Reference: Zhang & Lee (2025), arXiv:2502.11347.
"""

# =====================================================================
# TEX
# =====================================================================
with open('paper/remora_paper.tex', encoding='utf-8') as f:
    tex = f.read()

tee_tex = r"""
\section{Tamper-Proof Audit via Trusted Execution Environments}
\label{sec:tee}

\subsection{Motivation}

REMORA's audit trail (§\ref{sec:policy}) provides a chain of
\texttt{DecisionEnvelope} records signed by the REMORA engine.  However,
a software-only audit cannot guarantee that the recorded decision was
actually produced by the correct model under the correct policy: an
adversary with access to the inference host could substitute model
weights, alter the policy, or tamper with logs before signing.  Trusted
Execution Environments (TEEs) address this by cryptographically attesting
that the computation was performed inside an unmodified, hardware-isolated
enclave \cite{zhang2025tee}.

\subsection{Supported TEE Platforms}

REMORA's \textbf{TEE Audit Protocol} specifies the attestation
requirements for three supported platforms:

\begin{description}
  \item[AMD SEV-SNP] (Secure Encrypted Virtualization -- Secure Nested
    Paging).  Provides hardware memory encryption and CPU register
    isolation at the VM level.  Each VM boots with a measurement
    (SHA-384 hash of initial memory) published in an \emph{attestation
    report} signed by AMD's VCEK (Versioned Chip Endorsement Key).
    REMORA requirement: VM measurement must match the registered
    \texttt{remora-sev-measurement} in the governance ledger.

  \item[Intel TDX / SGX]  Intel Trust Domain Extensions (TDX, Xeon 4th
    gen+) and Software Guard Extensions (SGX) produce \emph{quotes}
    signed by the Intel Attestation Service (IAS) or the Data Center
    Attestation Primitives (DCAP) service.  REMORA requirement: enclave
    MRENCLAVE and MRSIGNER must match registered values; the quote
    must pass DCAP verification before any oracle key is injected.

  \item[NVIDIA Confidential Computing (H100/H200)]  NVIDIA's
    Hopper-generation GPUs provide a GPU attestation report (NRAS)
    covering both CPU and GPU memory, signed by the NVIDIA Certificate
    Authority.  REMORA requirement: the GPU attestation must cover the
    full inference session (from model load to response generation).
\end{description}

\subsection{DecisionEnvelope Attestation Format}

Each \texttt{DecisionEnvelope} produced by REMORA in TEE mode includes
an attestation extension:

\begin{verbatim}
{
  "envelope_id": "<UUID>",
  "verdict":     "ACCEPT | VERIFY | ABSTAIN | ESCALATE",
  "trust_score": 0.74,
  "timestamp":   "2026-05-31T09:00:00Z",
  "tee": {
    "platform":       "amd-sev-snp | intel-tdx | nvidia-h100",
    "measurement":    "<hex-encoded VM/enclave measurement>",
    "attestation_report_hash": "<SHA-256 of raw attestation report>",
    "vcek_cert_chain": "<base64-PEM>",
    "nonce":          "<32-byte request nonce>",
    "verified":       true
  },
  "policy_hash":  "<SHA-256 of OPA/Rego bundle>",
  "model_hash":   "<SHA-256 of model weights>",
  "oracle_ids":   ["groq-llama-8b", "groq-llama-70b", "mistral-7b"],
  "signature":    "<Ed25519 over envelope_id+verdict+trust_score+timestamp>"
}
\end{verbatim}

The \texttt{tee.verified} flag is set only after an attestation service
(AMD KDS, Intel DCAP, NVIDIA NRAS) confirms:
(i) the platform measurement matches the registered golden value,
(ii) the nonce matches the request nonce (replay prevention), and
(iii) the certificate chain is valid and not revoked.

\subsection{Verification Flow}

\begin{enumerate}[leftmargin=*,label=\arabic*.]
  \item \textbf{Launch}: TEE VM/enclave boots; measurement is recorded.
  \item \textbf{Registration}: Operator registers the golden measurement
        in the REMORA governance ledger (D1 database, §\ref{sec:policy}).
  \item \textbf{Attestation request}: On session start, the REMORA
        worker requests an attestation report with a fresh 32-byte nonce.
  \item \textbf{Remote verification}: Governance verifier calls the
        platform attestation service with the report and nonce.
  \item \textbf{Key injection}: Only after successful verification does
        the governance service inject the oracle API key into the enclave.
  \item \textbf{Execution}: Oracle calls, SE clustering, CRC calibration,
        PVD deliberation, and audit signing all run inside the TEE.
  \item \textbf{Audit submission}: Signed \texttt{DecisionEnvelope}
        (including \texttt{tee} block) is appended to the D1 audit ledger.
\end{enumerate}

\subsection{Implementation Status}

The TEE Audit Protocol is specified at the interface level; hardware
integration is pending availability of AMD SEV-SNP or Intel TDX
development environments.  The \texttt{DecisionEnvelope} dataclass
(\texttt{remora.assurance.decision\_envelope}) already includes a
\texttt{tee\_attestation: dict | None} field to hold the TEE block
when available.  The specification follows recommendations in Zhang
\& Lee (2025), who demonstrated that LLM inference inside confidential
computing enclaves achieves near-native performance with full attestation
overhead under 50~ms per session \cite{zhang2025tee}.

"""

# Insert before the Limitations section or before the Conclusion
conclusion_marker = r'\section{Conclusion}'
limitations_marker = r'\section{Limitations'

if limitations_marker in tex:
    insert_marker = tex[tex.find(limitations_marker):tex.find(limitations_marker)+50].split('\n')[0]
    tex = tex.replace(insert_marker, tee_tex + insert_marker)
    print("TEX: inserted before Limitations")
elif conclusion_marker in tex:
    tex = tex.replace(conclusion_marker, tee_tex + conclusion_marker)
    print("TEX: inserted before Conclusion")
else:
    print("WARNING: could not find Limitations or Conclusion marker in TEX")

with open('paper/remora_paper.tex', 'w', encoding='utf-8') as f:
    f.write(tex)

# =====================================================================
# MARKDOWN
# =====================================================================
with open('paper/remora_paper.md', encoding='utf-8') as f:
    md = f.read()

tee_md = """
## 8.3 Tamper-Proof Audit via Trusted Execution Environments

REMORA's software-only audit trail can be strengthened with hardware attestation from Trusted Execution Environments (TEEs), ensuring that the recorded decision was produced by the correct model under the correct policy inside an isolated enclave (Zhang & Lee, 2025).

**Supported platforms:**
- **AMD SEV-SNP**: Hardware memory encryption + VM-level isolation. Attestation report (SHA-384 measurement) signed by AMD VCEK.
- **Intel TDX/SGX**: Enclave quotes (MRENCLAVE + MRSIGNER) verified via Intel DCAP.
- **NVIDIA Confidential Computing (H100/H200)**: GPU attestation report (NRAS) covering full inference session.

**DecisionEnvelope attestation extension:**
```json
{
  "envelope_id": "<UUID>",
  "verdict": "ACCEPT | VERIFY | ABSTAIN | ESCALATE",
  "trust_score": 0.74,
  "tee": {
    "platform": "amd-sev-snp",
    "measurement": "<hex VM measurement>",
    "attestation_report_hash": "<SHA-256>",
    "nonce": "<32-byte>",
    "verified": true
  },
  "policy_hash": "<SHA-256 of OPA/Rego bundle>",
  "model_hash": "<SHA-256 of model weights>",
  "signature": "<Ed25519>"
}
```

**Verification flow:** Launch → Register golden measurement → Attestation request (with nonce) → Remote verification (AMD KDS / Intel DCAP / NVIDIA NRAS) → Key injection → Execution inside TEE → Signed envelope to D1 ledger.

**Implementation status:** Protocol specified; hardware integration pending TEE development environment availability. `remora.assurance.decision_envelope.DecisionEnvelope` includes `tee_attestation: dict | None` field. Zhang & Lee (2025) demonstrated <50 ms attestation overhead per session.

"""

# Find the limitations section in MD
lim_marker = "## 8. Limitations"
lim_marker2 = "## 8 Limitations"
lim_marker3 = "## Limitations"
conc_marker = "## Conclusion"
conc_marker2 = "## 9. Conclusion"

inserted = False
for marker in [lim_marker, lim_marker2, lim_marker3]:
    if marker in md:
        # Find 8.3 if it exists, else insert before the limitations section
        if "### 8.3" in md or "### 8.2" in md:
            # Insert as 8.3 after 8.2
            marker_82 = "### 8.2"
            if marker_82 in md:
                idx_82 = md.find(marker_82)
                idx_next = md.find("\n### ", idx_82 + 5)
                if idx_next < 0:
                    idx_next = md.find("\n## ", idx_82 + 5)
                if idx_next > 0:
                    md = md[:idx_next] + "\n" + tee_md + md[idx_next:]
                    inserted = True
                    print(f"MD: inserted after {marker_82}")
                    break
        else:
            md = md.replace(marker, tee_md + marker)
            inserted = True
            print(f"MD: inserted before {marker}")
            break

if not inserted:
    for marker in [conc_marker2, conc_marker]:
        if marker in md:
            md = md.replace(marker, tee_md + marker)
            inserted = True
            print(f"MD: inserted before {marker}")
            break

if not inserted:
    print("WARNING: could not find insertion point in MD")

with open('paper/remora_paper.md', 'w', encoding='utf-8') as f:
    f.write(md)

print("Done")
