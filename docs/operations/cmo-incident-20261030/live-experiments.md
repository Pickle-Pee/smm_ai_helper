# Live experiment ledger

All calls are explicit single POSTs, without retries. A reported zero usage is not proof of zero billing. Timeouts retain an unknown outcome. Raw incident evidence is retained only in the explicitly authorized production directory `/root/cmo-incident-20261030` (directory 0700, files 0600). This document contains metadata only.

Real POSTs: 31. Reported input tokens: 128410; output tokens: 16882 (includes reasoning). Billed cost: UNKNOWN.

| Source | Case | Request ID | Result | Original contract / gates | Duration s |
|---|---|---|---|---|---|
| synthetic | baseline | req_9624ec519d8e42dcac16562fbd5e415d | incomplete | NOT_RUN / NOT_RUN | 4.21 |
| synthetic | no_support_anyof | req_a85c7a92c2514b36844596f373901246 | completed | FAIL / NOT_RUN | 40.426 |
| synthetic | no_support_enums | req_40a81fa449134771a0dbb4e0cd838a0b | completed | PASS / PASS | 23.411 |
| synthetic | no_annotations | req_18ce557667fa46a6bda416a0c324fb6e | incomplete | NOT_RUN / NOT_RUN | 3.43 |
| synthetic | core_reduced | req_39f6e40cb5ff46cf97df4e9253578d9d | incomplete | NOT_RUN / NOT_RUN | 3.194 |
| synthetic | core_minimal | req_3b86b5f844124730973438d017020d97 | incomplete | NOT_RUN / NOT_RUN | 2.108 |
| synthetic | upstream_claims | req_bbbd24b266ca4ed19a475bd4d3756dcd | incomplete | NOT_RUN / NOT_RUN | 1.708 |
| synthetic | upstream_compact | req_807393f8d12149608e3bcfdda5215d05 | incomplete | NOT_RUN / NOT_RUN | 2.329 |
| synthetic | model_gpt5 | req_07f6c9c5f0ba414ab0691c4915b28788 | completed | PASS / PASS | 48.205 |
| synthetic | effort_medium | req_58a08c8f0f2345b19c04c075ca47ad9a | incomplete | NOT_RUN / NOT_RUN | 1.413 |
| synthetic | budget_32000 | req_f65de7f212f947e8970167480bc20138 | incomplete | NOT_RUN / NOT_RUN | 1.551 |
| synthetic | no_array_bounds | req_2accb6614304448dadf59535b4d22e2c | incomplete | NOT_RUN / NOT_RUN | 1.283 |
| incident reconstruction | baseline | req_deed7aa2b86147e5b46292d617cb30f0 | incomplete | NOT_RUN / NOT_RUN | 1.429 |
| incident reconstruction | equivalent_projection | req_5c42f62c3129466fbf1cc0233693c605 | completed | PASS / PASS | 49.707 |
| incident reconstruction | no_support_enums | req_1d9b7b05173244ab84ef0a2fbf493129 | completed | PASS / PASS | 47.47 |
| incident reconstruction | no_annotations | req_741e6a88886a437e9bb952769535ebf1 | incomplete | NOT_RUN / NOT_RUN | 3.342 |
| incident reconstruction | core_reduced | req_fcba3ca1794140acb7fb0f05677c9452 | incomplete | NOT_RUN / NOT_RUN | 2.818 |
| incident reconstruction | core_minimal | req_84678480e39d4c79996894e932cd70f6 | incomplete | NOT_RUN / NOT_RUN | 1.689 |
| incident reconstruction | upstream_claims | req_3c5c986982a540c694176aa8149ffb63 | incomplete | NOT_RUN / NOT_RUN | 2.701 |
| incident reconstruction | upstream_compact | req_f2db9d3c02f543e591a7b316bf0e33c9 | incomplete | NOT_RUN / NOT_RUN | 4.605 |
| incident reconstruction | model_gpt5 | UNKNOWN | ReadTimeout | NOT_RUN / NOT_RUN | 60.126 |
| incident reconstruction | effort_medium | req_10ff1477398747faa4cfb3b0030d805b | incomplete | NOT_RUN / NOT_RUN | 2.48 |
| incident reconstruction | budget_32000 | req_736671a759c84e37b300b0da18f61c76 | incomplete | NOT_RUN / NOT_RUN | 1.708 |
| incident reconstruction | no_array_bounds | req_0558d66e0fd645398aa3ebd5a344a598 | incomplete | NOT_RUN / NOT_RUN | 2.115 |
| incident reconstruction | no_numeric_structure | req_c7d023f9916a4867b8f469b17256b717 | incomplete | NOT_RUN / NOT_RUN | 2.678 |
| incident reconstruction | instructions_field | req_374b93e41def4399bdcd2b1ac30eefa2 | incomplete | NOT_RUN / NOT_RUN | 1.905 |
| incident reconstruction | baseline_confirmation | req_5dd3bb744fea4b5daf31a41e1fe2acb7 | incomplete | NOT_RUN / NOT_RUN | 2.217 |
| incident reconstruction | equivalent_projection_confirmation | req_5320ce93945a4dc3bb7c4e0db6a5c1ab | completed | PASS / PASS | 33.578 |
| incident reconstruction | history_5421c99 | req_bccda7645ee446849739eb83fc9d3ebb | incomplete | NOT_RUN / NOT_RUN | 4.121 |
| incident reconstruction | history_8e11a43 | req_5272fe8a41cb40dd9c840f7822584349 | incomplete | NOT_RUN / NOT_RUN | 4.215 |
| incident reconstruction | history_7f5b7cc | req_c7b9315342c444c6b7dee005821bb342 | incomplete | NOT_RUN / NOT_RUN | 2.303 |
