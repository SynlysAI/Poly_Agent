"""Knowledge base RAG/KG service.

The platform consumes already-prepared text cards and graph data. It does not
download papers, parse PDFs, or perform data cleaning.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import HTTPException

from app.schemas.knowledge import (
    KnowledgeCitation,
    KnowledgeGraphData,
    KnowledgeGraphEdge,
    KnowledgeGraphNode,
    KnowledgeGraphStats,
    KnowledgeHealthData,
    KnowledgeHit,
    KnowledgeQueryRequest,
    KnowledgeQueryResponse,
    KnowledgeSystem,
    KnowledgeSystemListData,
)


DEMO_SYSTEM_ID = "ai4s_fluoropolymer"

DEMO_BASE_DOCUMENTS: list[dict[str, Any]] = [
    {
        "source_id": "demo_card_fluoropolymer_dielectric",
        "title": "AI4S demo card: fluoropolymer dielectric-property design",
        "summary": (
            "Fluoropolymer dielectric performance is commonly discussed through "
            "repeat-unit polarity, fluorine content, free volume, crystallinity, "
            "and processing-induced morphology. AI4S workflows can combine graph "
            "features, computed descriptors, and experimental observations."
        ),
        "keywords": ["fluoropolymer", "dielectric", "AI4S", "descriptor"],
        "source": "demo_source",
        "doi": None,
        "url": None,
        "metadata": {
            "demo_source": True,
            "source_type": "demo_card",
            "material_family": "fluoropolymer",
            "properties": ["dielectric_constant", "thermal_stability"],
        },
    },
    {
        "source_id": "demo_card_thermal_stability",
        "title": "AI4S demo card: thermal stability and backbone chemistry",
        "summary": (
            "Thermal stability in fluorinated polymers is associated with C-F "
            "bond strength, backbone rigidity, chain packing, and degradation "
            "pathways. Candidate screening should keep measurement conditions "
            "and processing history attached to every property record."
        ),
        "keywords": ["thermal_stability", "fluoropolymer", "degradation"],
        "source": "demo_source",
        "doi": None,
        "url": None,
        "metadata": {
            "demo_source": True,
            "source_type": "demo_card",
            "material_family": "fluoropolymer",
            "properties": ["thermal_stability"],
        },
    },
    {
        "source_id": "demo_card_knowledge_graph",
        "title": "AI4S demo card: graph context for polymer knowledge reuse",
        "summary": (
            "A useful polymer knowledge graph connects monomers, polymers, target "
            "properties, measurement methods, datasets, applications, and papers. "
            "RAG answers should expose these graph links as evidence rather than "
            "only returning free text."
        ),
        "keywords": ["knowledge graph", "RAG", "polymer", "evidence"],
        "source": "demo_source",
        "doi": None,
        "url": None,
        "metadata": {
            "demo_source": True,
            "source_type": "demo_card",
            "material_family": "fluoropolymer",
            "properties": ["knowledge_graph"],
        },
    },
]

DEMO_PAPER_DOCUMENTS: list[dict[str, Any]] = [
    {
        "source_id": "paper_nature_nanotech_2024_polymer_nanocomposite_dielectrics",
        "title": "Polymer nanocomposite dielectrics for capacitive energy storage",
        "summary": (
            "Nature Nanotechnology review of polymer nanocomposite dielectrics, "
            "covering high-k fillers, interface engineering, breakdown strength, "
            "energy density, efficiency, and scalable film capacitor design."
        ),
        "keywords": ["polymer nanocomposite", "dielectric", "energy storage", "capacitor", "interface", "breakdown strength", "介电", "储能"],
        "source": "Nature Nanotechnology",
        "doi": "10.1038/s41565-023-01541-w",
        "url": "https://doi.org/10.1038/s41565-023-01541-w",
        "metadata": {
            "demo_source": True,
            "source_type": "paper_seed",
            "journal": "Nature Nanotechnology",
            "year": 2024,
            "authors": ["Yang", "Guo", "Xu", "Ren", "Wang", "Li", "Zhang", "Nan", "Shen"],
            "themes": ["polymer_nanocomposite", "energy_storage", "interface_engineering", "breakdown_strength"],
        },
    },
    {
        "source_id": "paper_scirep_2016_ml_polymer_dielectrics",
        "title": "Machine Learning Strategy for Accelerated Design of Polymer Dielectrics",
        "summary": (
            "Scientific Reports paper demonstrating polymer fingerprints, first-principles data, "
            "machine learning prediction, and genetic-algorithm search for dielectric polymer design."
        ),
        "keywords": ["machine learning", "polymer dielectrics", "fingerprint", "genetic algorithm", "AI4S", "机器学习", "介电聚合物"],
        "source": "Scientific Reports",
        "doi": "10.1038/srep20952",
        "url": "https://doi.org/10.1038/srep20952",
        "metadata": {
            "demo_source": True,
            "source_type": "paper_seed",
            "journal": "Scientific Reports",
            "year": 2016,
            "authors": ["Mannodi-Kanakkithodi", "Pilania", "Huan", "Lookman", "Ramprasad"],
            "themes": ["machine_learning", "descriptor", "high_throughput", "polymer_design"],
        },
    },
    {
        "source_id": "paper_natcomm_2014_all_organic_polymer_dielectrics",
        "title": "Rational design of all organic polymer dielectrics",
        "summary": (
            "Nature Communications study on rational molecular design of all-organic polymer dielectrics, "
            "linking polymer chemistry, dielectric response, and energy-storage targets."
        ),
        "keywords": ["all-organic", "polymer dielectric", "rational design", "energy storage", "molecular design", "全有机", "分子设计"],
        "source": "Nature Communications",
        "doi": "10.1038/ncomms5845",
        "url": "https://doi.org/10.1038/ncomms5845",
        "metadata": {
            "demo_source": True,
            "source_type": "paper_seed",
            "journal": "Nature Communications",
            "year": 2014,
            "authors": ["Sharma", "Ramakrishnan", "Chernatynskiy", "Brenner", "Sankaranarayanan"],
            "themes": ["all_organic", "molecular_design", "energy_storage", "dielectric_constant"],
        },
    },
    {
        "source_id": "paper_adma_2016_rational_codesign",
        "title": "Rational Co-Design of Polymer Dielectrics for Energy Storage",
        "summary": (
            "Advanced Materials perspective showing how high-throughput computation, experiments, "
            "and polymer subclass exploration can co-design electrostatic energy-storage dielectrics."
        ),
        "keywords": ["co-design", "high-throughput", "polyurea", "polyimide", "polymer dielectric", "energy storage", "共设计"],
        "source": "Advanced Materials",
        "doi": "10.1002/adma.201600377",
        "url": "https://doi.org/10.1002/adma.201600377",
        "metadata": {
            "demo_source": True,
            "source_type": "paper_seed",
            "journal": "Advanced Materials",
            "year": 2016,
            "authors": ["Mannodi-Kanakkithodi", "Treich", "Huan", "Ma", "Tefferi", "Cao", "Sotzing", "Ramprasad"],
            "themes": ["high_throughput", "polymer_design", "energy_storage", "descriptor"],
        },
    },
    {
        "source_id": "paper_annurev_2015_high_energy_density",
        "title": "Polymer-Based Dielectrics with High Energy Storage Density",
        "summary": (
            "Annual Review of Materials Research article summarizing polymer and nanocomposite routes "
            "to higher dielectric polarization, breakdown strength, and energy density."
        ),
        "keywords": ["high energy density", "polymer-based dielectrics", "nanocomposite", "breakdown strength", "film capacitor", "高能量密度"],
        "source": "Annual Review of Materials Research",
        "doi": "10.1146/annurev-matsci-070214-021017",
        "url": "https://doi.org/10.1146/annurev-matsci-070214-021017",
        "metadata": {
            "demo_source": True,
            "source_type": "paper_seed",
            "journal": "Annual Review of Materials Research",
            "year": 2015,
            "authors": ["Chen", "Shen", "Zhang", "Zhang"],
            "themes": ["energy_density", "nanocomposite", "breakdown_strength", "film_capacitor"],
        },
    },
    {
        "source_id": "paper_nsr_2017_polymer_nanocomposite",
        "title": "Polymer nanocomposite dielectrics for electrical energy storage",
        "summary": (
            "National Science Review review covering filler design, interfacial polarization, "
            "breakdown reliability, and structure-property trade-offs in polymer nanocomposite dielectrics."
        ),
        "keywords": ["polymer nanocomposite", "electrical energy storage", "interface", "filler", "breakdown", "纳米复合"],
        "source": "National Science Review",
        "doi": "10.1093/nsr/nww066",
        "url": "https://doi.org/10.1093/nsr/nww066",
        "metadata": {
            "demo_source": True,
            "source_type": "paper_seed",
            "journal": "National Science Review",
            "year": 2017,
            "authors": ["Shen", "Zhang", "Li", "Lin", "Nan"],
            "themes": ["polymer_nanocomposite", "interface_engineering", "energy_storage", "filler_design"],
        },
    },
    {
        "source_id": "paper_jap_2020_high_temperature_polymer_dielectrics",
        "title": "Advanced polymer dielectrics for high temperature capacitive energy storage",
        "summary": (
            "Journal of Applied Physics perspective on high-temperature polymer dielectrics, "
            "carrier transport, thermal-electrical stress, and capacitor performance relationships."
        ),
        "keywords": ["high temperature", "capacitive energy storage", "polymer dielectric", "carrier transport", "thermal stability", "高温", "热稳定"],
        "source": "Journal of Applied Physics",
        "doi": "10.1063/5.0009650",
        "url": "https://doi.org/10.1063/5.0009650",
        "metadata": {
            "demo_source": True,
            "source_type": "paper_seed",
            "journal": "Journal of Applied Physics",
            "year": 2020,
            "authors": ["Zhou", "Wang"],
            "themes": ["high_temperature", "thermal_stability", "carrier_transport", "energy_storage"],
        },
    },
    {
        "source_id": "paper_chem_soc_rev_2021_high_temperature",
        "title": "Dielectric polymers for high-temperature capacitive energy storage",
        "summary": (
            "Chemical Society Reviews article on molecular, trap, and structural strategies for "
            "polymer dielectric capacitors operating under elevated temperature."
        ),
        "keywords": ["high-temperature", "capacitive energy storage", "dielectric polymers", "molecular structure", "carrier traps", "高温储能"],
        "source": "Chemical Society Reviews",
        "doi": "10.1039/d0cs00765j",
        "url": "https://doi.org/10.1039/d0cs00765j",
        "metadata": {
            "demo_source": True,
            "source_type": "paper_seed",
            "journal": "Chemical Society Reviews",
            "year": 2021,
            "authors": ["Li", "Chen", "Ai", "Han", "Liu", "Shen", "Nan"],
            "themes": ["high_temperature", "thermal_stability", "carrier_trap", "molecular_design"],
        },
    },
    {
        "source_id": "paper_pmatsci_2023_carrier_traps",
        "title": "Polymer dielectrics for high-temperature energy storage: Constructing carrier traps",
        "summary": (
            "Progress in Materials Science review focused on carrier-trap construction as a route "
            "to suppress conduction loss and improve high-temperature energy storage."
        ),
        "keywords": ["carrier traps", "high-temperature", "energy storage", "conduction loss", "polymer dielectrics", "载流子陷阱"],
        "source": "Progress in Materials Science",
        "doi": "10.1016/j.pmatsci.2023.101208",
        "url": "https://doi.org/10.1016/j.pmatsci.2023.101208",
        "metadata": {
            "demo_source": True,
            "source_type": "paper_seed",
            "journal": "Progress in Materials Science",
            "year": 2023,
            "authors": ["Zha", "Xiao", "Wan", "Wang", "Dang", "Chen"],
            "themes": ["carrier_trap", "high_temperature", "thermal_stability", "breakdown_strength"],
        },
    },
    {
        "source_id": "paper_adma_2022_ultrathin_all_organic",
        "title": "Scalable Ultrathin All-Organic Polymer Dielectric Films for High-Temperature Capacitive Energy Storage",
        "summary": (
            "Advanced Materials work on scalable ultrathin all-organic dielectric films for "
            "high-temperature capacitive energy storage and efficiency retention."
        ),
        "keywords": ["ultrathin film", "all-organic", "high-temperature", "capacitive energy storage", "scalable", "超薄膜"],
        "source": "Advanced Materials",
        "doi": "10.1002/adma.202207421",
        "url": "https://doi.org/10.1002/adma.202207421",
        "metadata": {
            "demo_source": True,
            "source_type": "paper_seed",
            "journal": "Advanced Materials",
            "year": 2022,
            "authors": ["Ren", "Yang", "Zhou", "Wang"],
            "themes": ["all_organic", "thin_film", "high_temperature", "energy_storage"],
        },
    },
    {
        "source_id": "paper_adma_2026_high_temperature_all_organic",
        "title": "High-Temperature All-Organic Polymer Dielectrics for Capacitive Energy Storage",
        "summary": (
            "Advanced Materials review of all-organic polymer dielectric design under combined "
            "thermal and electrical stress, emphasizing molecular structure and storage performance."
        ),
        "keywords": ["all-organic", "high-temperature", "polymer dielectrics", "capacitive energy storage", "molecular structure"],
        "source": "Advanced Materials",
        "doi": "10.1002/adma.202513978",
        "url": "https://doi.org/10.1002/adma.202513978",
        "metadata": {
            "demo_source": True,
            "source_type": "paper_seed",
            "journal": "Advanced Materials",
            "year": 2026,
            "authors": ["Zhou", "Chen", "Cheng", "Liu"],
            "themes": ["all_organic", "high_temperature", "thermal_stability", "molecular_design"],
        },
    },
    {
        "source_id": "paper_ees_2026_ml_high_temperature",
        "title": "Machine learning driven design of polymer dielectrics for high temperature capacitive energy storage",
        "summary": (
            "Energy & Environmental Science paper using machine-learning and high-throughput screening "
            "to identify high-temperature polymer dielectric candidates."
        ),
        "keywords": ["machine learning", "high-throughput", "high temperature", "polymer dielectrics", "capacitive energy storage", "AI4S"],
        "source": "Energy & Environmental Science",
        "doi": "10.1039/d6ee01953f",
        "url": "https://doi.org/10.1039/d6ee01953f",
        "metadata": {
            "demo_source": True,
            "source_type": "paper_seed",
            "journal": "Energy & Environmental Science",
            "year": 2026,
            "authors": ["Liu", "Cheng", "Li", "Wang", "Zhou", "He", "Yuan"],
            "themes": ["machine_learning", "high_throughput", "high_temperature", "polymer_design"],
        },
    },
    {
        "source_id": "paper_chemmater_2021_polyg2g",
        "title": "polyG2G: A Novel Machine Learning Algorithm Applied to the Generative Design of Polymer Dielectrics",
        "summary": (
            "Chemistry of Materials paper on generative machine learning for polymer dielectrics, "
            "useful for connecting RAG evidence to AI4S candidate generation."
        ),
        "keywords": ["polyG2G", "generative design", "machine learning", "polymer dielectric", "candidate generation", "生成式设计"],
        "source": "Chemistry of Materials",
        "doi": "10.1021/acs.chemmater.1c02061",
        "url": "https://doi.org/10.1021/acs.chemmater.1c02061",
        "metadata": {
            "demo_source": True,
            "source_type": "paper_seed",
            "journal": "Chemistry of Materials",
            "year": 2021,
            "authors": ["Gurnani", "Kuenneth", "Ramprasad"],
            "themes": ["machine_learning", "generative_design", "descriptor", "polymer_design"],
        },
    },
    {
        "source_id": "paper_commatsci_2025_ml_advances",
        "title": "Machine learning research advances in energy storage polymer-based dielectrics",
        "summary": (
            "Computational Materials Science review summarizing machine-learning datasets, descriptors, "
            "modeling workflows, and screening targets for energy-storage polymer dielectrics."
        ),
        "keywords": ["machine learning", "energy storage", "polymer-based dielectrics", "descriptor", "screening", "数据集"],
        "source": "Computational Materials Science",
        "doi": "10.1016/j.commatsci.2024.113651",
        "url": "https://doi.org/10.1016/j.commatsci.2024.113651",
        "metadata": {
            "demo_source": True,
            "source_type": "paper_seed",
            "journal": "Computational Materials Science",
            "year": 2025,
            "authors": ["Yuan", "Yue", "Zhang", "Feng", "Chen"],
            "themes": ["machine_learning", "descriptor", "energy_storage", "dataset"],
        },
    },
    {
        "source_id": "paper_ensm_2022_advanced_dielectric_polymers",
        "title": "Advanced dielectric polymers for energy storage",
        "summary": (
            "Energy Storage Materials review of advanced dielectric polymers, including polymer structure, "
            "relaxor behavior, and film capacitor energy-storage performance."
        ),
        "keywords": ["advanced dielectric polymers", "energy storage", "relaxor", "film capacitor", "polymer structure"],
        "source": "Energy Storage Materials",
        "doi": "10.1016/j.ensm.2021.10.010",
        "url": "https://doi.org/10.1016/j.ensm.2021.10.010",
        "metadata": {
            "demo_source": True,
            "source_type": "paper_seed",
            "journal": "Energy Storage Materials",
            "year": 2022,
            "authors": ["Wu", "Zhu", "Huang", "Liu", "Wang"],
            "themes": ["polymer_design", "energy_storage", "dielectric_constant", "film_capacitor"],
        },
    },
    {
        "source_id": "paper_adfm_2021_ferroelectric_nanocomposites",
        "title": "Enabling High-Energy-Density High-Efficiency Ferroelectric Polymer Nanocomposites with Rationally Designed Nanofillers",
        "summary": (
            "Advanced Functional Materials paper on rational nanofiller design in ferroelectric polymer "
            "nanocomposites to improve energy density and efficiency."
        ),
        "keywords": ["ferroelectric polymer", "nanofiller", "PVDF", "energy density", "efficiency", "铁电聚合物"],
        "source": "Advanced Functional Materials",
        "doi": "10.1002/adfm.202006739",
        "url": "https://doi.org/10.1002/adfm.202006739",
        "metadata": {
            "demo_source": True,
            "source_type": "paper_seed",
            "journal": "Advanced Functional Materials",
            "year": 2021,
            "authors": ["Li", "Liu", "Wang", "Chen"],
            "themes": ["pvdf", "ferroelectric_polymer", "filler_design", "energy_density"],
        },
    },
    {
        "source_id": "paper_adma_2014_ternary_ferroelectric",
        "title": "High Energy and Power Density Capacitors from Solution-Processed Ternary Ferroelectric Polymer Nanocomposites",
        "summary": (
            "Advanced Materials paper on solution-processed ternary ferroelectric polymer nanocomposites "
            "for high energy and power density capacitors."
        ),
        "keywords": ["ferroelectric polymer", "ternary nanocomposite", "solution processed", "PVDF", "energy density", "power density"],
        "source": "Advanced Materials",
        "doi": "10.1002/adma.201402106",
        "url": "https://doi.org/10.1002/adma.201402106",
        "metadata": {
            "demo_source": True,
            "source_type": "paper_seed",
            "journal": "Advanced Materials",
            "year": 2014,
            "authors": ["Li", "Chen", "Gadinski", "Zhang", "Wang"],
            "themes": ["pvdf", "ferroelectric_polymer", "nanocomposite", "energy_density"],
        },
    },
    {
        "source_id": "paper_polymer_2009_pvdf_terpolymers",
        "title": "Energy storage study of ferroelectric poly(vinylidene fluoride-trifluoroethylene-chlorotrifluoroethylene) terpolymers",
        "summary": (
            "Polymer study of P(VDF-TrFE-CTFE) terpolymers, connecting fluoropolymer composition, "
            "ferroelectric response, and recoverable energy-storage behavior."
        ),
        "keywords": ["PVDF", "P(VDF-TrFE-CTFE)", "terpolymer", "ferroelectric", "energy storage", "氟聚合物"],
        "source": "Polymer",
        "doi": "10.1016/j.polymer.2008.11.005",
        "url": "https://doi.org/10.1016/j.polymer.2008.11.005",
        "metadata": {
            "demo_source": True,
            "source_type": "paper_seed",
            "journal": "Polymer",
            "year": 2009,
            "authors": ["Zhang", "Bharti", "Zhao"],
            "themes": ["pvdf", "terpolymer", "ferroelectric_polymer", "energy_storage"],
        },
    },
    {
        "source_id": "paper_apl_2012_pvdf_hfp_blends",
        "title": "Intermolecular interactions and high dielectric energy storage density in poly(vinylidene fluoride-hexafluoropropylene)/poly(vinylidene fluoride) blends",
        "summary": (
            "Applied Physics Letters paper connecting PVDF-HFP/PVDF blend interactions with high "
            "dielectric energy-storage density."
        ),
        "keywords": ["PVDF-HFP", "PVDF", "blend", "intermolecular interaction", "dielectric energy storage", "共混"],
        "source": "Applied Physics Letters",
        "doi": "10.1063/1.4730603",
        "url": "https://doi.org/10.1063/1.4730603",
        "metadata": {
            "demo_source": True,
            "source_type": "paper_seed",
            "journal": "Applied Physics Letters",
            "year": 2012,
            "authors": ["Rahimabady", "Mirshekarloo", "Yao", "Lu", "Zhu"],
            "themes": ["pvdf", "blend", "dielectric_constant", "energy_density"],
        },
    },
    {
        "source_id": "paper_jmc_c_2019_mxene_pvdf",
        "title": "Multilayer-structured transparent MXene/PVDF film with excellent dielectric and energy storage performance",
        "summary": (
            "Journal of Materials Chemistry C paper on multilayer MXene/PVDF transparent films, "
            "highlighting architecture control for dielectric loss and energy-storage performance."
        ),
        "keywords": ["MXene", "PVDF", "multilayer", "transparent film", "dielectric loss", "energy storage", "多层结构"],
        "source": "Journal of Materials Chemistry C",
        "doi": "10.1039/c9tc02715g",
        "url": "https://doi.org/10.1039/c9tc02715g",
        "metadata": {
            "demo_source": True,
            "source_type": "paper_seed",
            "journal": "Journal of Materials Chemistry C",
            "year": 2019,
            "authors": ["Li", "Song", "Zhong", "Qian", "Tan", "Wu", "Chu", "Nie", "Ran"],
            "themes": ["pvdf", "multilayer", "filler_design", "dielectric_loss"],
        },
    },
    {
        "source_id": "paper_rsc_adv_2021_crosslinked_fluoropolymer",
        "title": "Enhanced energy storage density of all-organic fluoropolymer composite dielectric via introducing crosslinked structure",
        "summary": (
            "RSC Advances paper on all-organic fluoropolymer composite dielectric films, showing "
            "crosslinked structures as a route to higher energy-storage density."
        ),
        "keywords": ["fluoropolymer", "all-organic", "crosslinked", "energy storage density", "dielectric", "交联"],
        "source": "RSC Advances",
        "doi": "10.1039/d1ra01423d",
        "url": "https://doi.org/10.1039/d1ra01423d",
        "metadata": {
            "demo_source": True,
            "source_type": "paper_seed",
            "journal": "RSC Advances",
            "year": 2021,
            "authors": ["Li", "Yang", "Wang", "Pang", "Shi", "Ma", "Zhu"],
            "themes": ["fluoropolymer", "all_organic", "crosslinking", "energy_density"],
        },
    },
    {
        "source_id": "paper_jmca_2021_crosslinked_dielectric",
        "title": "Crosslinked dielectric materials for high-temperature capacitive energy storage",
        "summary": (
            "Journal of Materials Chemistry A paper on crosslinked dielectric materials for maintaining "
            "capacitive energy storage under high-temperature operation."
        ),
        "keywords": ["crosslinked", "high-temperature", "capacitive energy storage", "dielectric materials", "thermal stability"],
        "source": "Journal of Materials Chemistry A",
        "doi": "10.1039/d1ta00288k",
        "url": "https://doi.org/10.1039/d1ta00288k",
        "metadata": {
            "demo_source": True,
            "source_type": "paper_seed",
            "journal": "Journal of Materials Chemistry A",
            "year": 2021,
            "authors": ["Tang", "Zhou", "Wang"],
            "themes": ["crosslinking", "high_temperature", "thermal_stability", "energy_storage"],
        },
    },
]

DEMO_DOCUMENTS: list[dict[str, Any]] = [*DEMO_BASE_DOCUMENTS, *DEMO_PAPER_DOCUMENTS]

DEMO_BASE_NODES: list[dict[str, Any]] = [
    {"id": "material_fluoropolymer", "label": "Fluoropolymer", "type": "Material", "score": 1.0, "properties": {"demo_source": True}},
    {"id": "polymer_pvdf", "label": "PVDF", "type": "Polymer", "score": 0.96, "properties": {"full_name": "poly(vinylidene fluoride)", "demo_source": True}},
    {"id": "polymer_pvdf_hfp", "label": "PVDF-HFP", "type": "Polymer", "score": 0.9, "properties": {"full_name": "poly(vinylidene fluoride-hexafluoropropylene)", "demo_source": True}},
    {"id": "polymer_pvdf_trfe_ctfe", "label": "P(VDF-TrFE-CTFE)", "type": "Polymer", "score": 0.88, "properties": {"family": "fluorinated terpolymer", "demo_source": True}},
    {"id": "material_polymer_nanocomposite", "label": "Polymer nanocomposite dielectric", "type": "Material", "score": 0.92, "properties": {"demo_source": True}},
    {"id": "monomer_vdf", "label": "Vinylidene fluoride", "type": "Monomer", "score": 0.9, "properties": {"smiles_hint": "C=C(F)F", "demo_source": True}},
    {"id": "monomer_hfp", "label": "Hexafluoropropylene", "type": "Monomer", "score": 0.82, "properties": {"demo_source": True}},
    {"id": "monomer_trfe", "label": "Trifluoroethylene", "type": "Monomer", "score": 0.8, "properties": {"demo_source": True}},
    {"id": "monomer_ctfe", "label": "Chlorotrifluoroethylene", "type": "Monomer", "score": 0.78, "properties": {"demo_source": True}},
    {"id": "property_dielectric", "label": "Dielectric constant", "type": "Property", "score": 0.95, "properties": {"unit": "relative", "demo_source": True}},
    {"id": "property_energy_density", "label": "Energy density", "type": "Property", "score": 0.95, "properties": {"unit": "J/cm3", "demo_source": True}},
    {"id": "property_breakdown", "label": "Breakdown strength", "type": "Property", "score": 0.93, "properties": {"unit": "MV/m", "demo_source": True}},
    {"id": "property_efficiency", "label": "Charge-discharge efficiency", "type": "Property", "score": 0.88, "properties": {"unit": "%", "demo_source": True}},
    {"id": "property_dielectric_loss", "label": "Dielectric loss", "type": "Property", "score": 0.86, "properties": {"demo_source": True}},
    {"id": "property_thermal", "label": "Thermal stability", "type": "Property", "score": 0.91, "properties": {"unit": "C", "demo_source": True}},
    {"id": "strategy_interface", "label": "Interface engineering", "type": "Strategy", "score": 0.89, "properties": {"demo_source": True}},
    {"id": "strategy_filler", "label": "Rational filler design", "type": "Strategy", "score": 0.87, "properties": {"demo_source": True}},
    {"id": "strategy_crosslinking", "label": "Crosslinking", "type": "Strategy", "score": 0.85, "properties": {"demo_source": True}},
    {"id": "strategy_multilayer", "label": "Multilayer architecture", "type": "Strategy", "score": 0.84, "properties": {"demo_source": True}},
    {"id": "strategy_all_organic", "label": "All-organic design", "type": "Strategy", "score": 0.83, "properties": {"demo_source": True}},
    {"id": "strategy_carrier_trap", "label": "Carrier trap construction", "type": "Strategy", "score": 0.82, "properties": {"demo_source": True}},
    {"id": "method_graph_features", "label": "Graph descriptors", "type": "Method", "score": 0.86, "properties": {"demo_source": True}},
    {"id": "method_machine_learning", "label": "Machine learning screening", "type": "Method", "score": 0.9, "properties": {"demo_source": True}},
    {"id": "method_high_throughput", "label": "High-throughput computation", "type": "Method", "score": 0.88, "properties": {"demo_source": True}},
    {"id": "method_generative_design", "label": "Generative polymer design", "type": "Method", "score": 0.82, "properties": {"demo_source": True}},
    {"id": "dataset_ai4s_demo", "label": "AI4S demo dataset", "type": "Dataset", "score": 0.82, "properties": {"demo_source": True}},
    {"id": "dataset_paper_seed", "label": "DOI-traceable paper seed", "type": "Dataset", "score": 0.84, "properties": {"document_count": len(DEMO_PAPER_DOCUMENTS), "demo_source": True}},
    {"id": "application_energy", "label": "Energy storage dielectric film", "type": "Application", "score": 0.78, "properties": {"demo_source": True}},
    {"id": "application_high_temperature_capacitor", "label": "High-temperature film capacitor", "type": "Application", "score": 0.8, "properties": {"demo_source": True}},
    {"id": "paper_demo_dielectric", "label": "Demo dielectric design card", "type": "Paper", "score": 0.72, "properties": {"source_id": "demo_card_fluoropolymer_dielectric", "demo_source": True}},
]

THEME_NODE_MAP = {
    "all_organic": "strategy_all_organic",
    "breakdown_strength": "property_breakdown",
    "carrier_transport": "strategy_carrier_trap",
    "carrier_trap": "strategy_carrier_trap",
    "crosslinking": "strategy_crosslinking",
    "dataset": "dataset_ai4s_demo",
    "descriptor": "method_graph_features",
    "dielectric_constant": "property_dielectric",
    "dielectric_loss": "property_dielectric_loss",
    "energy_density": "property_energy_density",
    "energy_storage": "application_energy",
    "ferroelectric_polymer": "polymer_pvdf",
    "filler_design": "strategy_filler",
    "film_capacitor": "application_energy",
    "fluoropolymer": "material_fluoropolymer",
    "generative_design": "method_generative_design",
    "high_temperature": "application_high_temperature_capacitor",
    "high_throughput": "method_high_throughput",
    "interface_engineering": "strategy_interface",
    "machine_learning": "method_machine_learning",
    "molecular_design": "strategy_all_organic",
    "multilayer": "strategy_multilayer",
    "nanocomposite": "material_polymer_nanocomposite",
    "polymer_design": "method_high_throughput",
    "polymer_nanocomposite": "material_polymer_nanocomposite",
    "pvdf": "polymer_pvdf",
    "terpolymer": "polymer_pvdf_trfe_ctfe",
    "thermal_stability": "property_thermal",
    "thin_film": "strategy_multilayer",
}


def _paper_node(doc: dict[str, Any]) -> dict[str, Any]:
    metadata = doc.get("metadata", {})
    return {
        "id": f"node_{doc['source_id']}",
        "label": doc["title"],
        "type": "Paper",
        "score": 0.75,
        "properties": {
            "source_id": doc["source_id"],
            "doi": doc.get("doi"),
            "url": doc.get("url"),
            "journal": metadata.get("journal"),
            "year": metadata.get("year"),
            "authors": metadata.get("authors", []),
            "demo_source": True,
        },
    }


DEMO_NODES: list[dict[str, Any]] = [*DEMO_BASE_NODES, *[_paper_node(doc) for doc in DEMO_PAPER_DOCUMENTS]]


DEMO_BASE_EDGES: list[dict[str, Any]] = [
    {"id": "edge_material_polymer", "source": "material_fluoropolymer", "target": "polymer_pvdf", "type": "SIMILAR_TO", "weight": 0.8, "properties": {"demo_source": True}},
    {"id": "edge_pvdf_monomer", "source": "polymer_pvdf", "target": "monomer_vdf", "type": "HAS_MONOMER", "weight": 1.0, "properties": {"demo_source": True}},
    {"id": "edge_pvdf_hfp_vdf", "source": "polymer_pvdf_hfp", "target": "monomer_vdf", "type": "HAS_MONOMER", "weight": 0.92, "properties": {"demo_source": True}},
    {"id": "edge_pvdf_hfp_hfp", "source": "polymer_pvdf_hfp", "target": "monomer_hfp", "type": "HAS_MONOMER", "weight": 0.9, "properties": {"demo_source": True}},
    {"id": "edge_terpolymer_vdf", "source": "polymer_pvdf_trfe_ctfe", "target": "monomer_vdf", "type": "HAS_MONOMER", "weight": 0.9, "properties": {"demo_source": True}},
    {"id": "edge_terpolymer_trfe", "source": "polymer_pvdf_trfe_ctfe", "target": "monomer_trfe", "type": "HAS_MONOMER", "weight": 0.88, "properties": {"demo_source": True}},
    {"id": "edge_terpolymer_ctfe", "source": "polymer_pvdf_trfe_ctfe", "target": "monomer_ctfe", "type": "HAS_MONOMER", "weight": 0.86, "properties": {"demo_source": True}},
    {"id": "edge_pvdf_dielectric", "source": "polymer_pvdf", "target": "property_dielectric", "type": "HAS_PROPERTY", "weight": 0.95, "properties": {"demo_source": True}},
    {"id": "edge_pvdf_thermal", "source": "polymer_pvdf", "target": "property_thermal", "type": "HAS_PROPERTY", "weight": 0.88, "properties": {"demo_source": True}},
    {"id": "edge_pvdf_energy_density", "source": "polymer_pvdf", "target": "property_energy_density", "type": "HAS_PROPERTY", "weight": 0.9, "properties": {"demo_source": True}},
    {"id": "edge_dielectric_method", "source": "property_dielectric", "target": "method_graph_features", "type": "MEASURED_BY", "weight": 0.65, "properties": {"demo_source": True}},
    {"id": "edge_energy_ml", "source": "property_energy_density", "target": "method_machine_learning", "type": "OPTIMIZED_BY", "weight": 0.78, "properties": {"demo_source": True}},
    {"id": "edge_thermal_trap", "source": "property_thermal", "target": "strategy_carrier_trap", "type": "IMPROVED_BY", "weight": 0.76, "properties": {"demo_source": True}},
    {"id": "edge_interface_breakdown", "source": "strategy_interface", "target": "property_breakdown", "type": "IMPROVES", "weight": 0.82, "properties": {"demo_source": True}},
    {"id": "edge_filler_dielectric", "source": "strategy_filler", "target": "property_dielectric", "type": "TUNES", "weight": 0.76, "properties": {"demo_source": True}},
    {"id": "edge_crosslinking_thermal", "source": "strategy_crosslinking", "target": "property_thermal", "type": "IMPROVES", "weight": 0.8, "properties": {"demo_source": True}},
    {"id": "edge_multilayer_loss", "source": "strategy_multilayer", "target": "property_dielectric_loss", "type": "SUPPRESSES", "weight": 0.74, "properties": {"demo_source": True}},
    {"id": "edge_dataset_polymer", "source": "dataset_ai4s_demo", "target": "polymer_pvdf", "type": "REPORTED_IN", "weight": 0.82, "properties": {"demo_source": True}},
    {"id": "edge_seed_dataset_material", "source": "dataset_paper_seed", "target": "material_fluoropolymer", "type": "COVERS", "weight": 0.82, "properties": {"demo_source": True}},
    {"id": "edge_seed_dataset_method", "source": "dataset_paper_seed", "target": "method_machine_learning", "type": "COVERS", "weight": 0.78, "properties": {"demo_source": True}},
    {"id": "edge_paper_dataset", "source": "paper_demo_dielectric", "target": "dataset_ai4s_demo", "type": "REPORTED_IN", "weight": 0.78, "properties": {"demo_source": True}},
    {"id": "edge_application_property", "source": "application_energy", "target": "property_dielectric", "type": "OPTIMIZED_FOR", "weight": 0.9, "properties": {"demo_source": True}},
    {"id": "edge_high_temp_thermal", "source": "application_high_temperature_capacitor", "target": "property_thermal", "type": "REQUIRES", "weight": 0.88, "properties": {"demo_source": True}},
    {"id": "edge_high_temp_breakdown", "source": "application_high_temperature_capacitor", "target": "property_breakdown", "type": "REQUIRES", "weight": 0.84, "properties": {"demo_source": True}},
]


def _paper_edges(doc: dict[str, Any]) -> list[dict[str, Any]]:
    source = f"node_{doc['source_id']}"
    edges = [
        {
            "id": f"edge_{doc['source_id']}_seed",
            "source": source,
            "target": "dataset_paper_seed",
            "type": "IN_SEED_SET",
            "weight": 0.72,
            "properties": {"demo_source": True},
        }
    ]
    for theme in doc.get("metadata", {}).get("themes", []):
        target = THEME_NODE_MAP.get(theme)
        if target:
            edges.append({
                "id": f"edge_{doc['source_id']}_{theme}",
                "source": source,
                "target": target,
                "type": "SUPPORTS",
                "weight": 0.68,
                "properties": {"demo_source": True, "theme": theme},
            })
    return edges


DEMO_EDGES: list[dict[str, Any]] = [
    *DEMO_BASE_EDGES,
    *[edge for doc in DEMO_PAPER_DOCUMENTS for edge in _paper_edges(doc)],
]


class KnowledgeService:
    """Facade for LightRAG-backed querying and demo graph browsing."""

    def list_systems(self) -> KnowledgeSystemListData:
        graph = self.get_graph(DEMO_SYSTEM_ID)
        items = [
            KnowledgeSystem(
                system_id=DEMO_SYSTEM_ID,
                name="AI4S 氟聚合物材料体系",
                domain="AI4S",
                material_family="fluoropolymer",
                description="面向氟聚合物介电、热稳定与结构-性能关系的 demo 知识库。",
                is_demo=True,
                tags=["AI4S", "fluoropolymer", "RAG", "knowledge_graph"],
                document_count=graph.stats.document_count,
                entity_count=graph.stats.entity_count,
                relation_count=graph.stats.relation_count,
            )
        ]
        return KnowledgeSystemListData(items=items, total=len(items))

    def health(self) -> KnowledgeHealthData:
        base_url = self._base_url()
        systems = [DEMO_SYSTEM_ID]
        if not base_url:
            return KnowledgeHealthData(
                status="warning",
                configured=False,
                demo_available=True,
                message="LightRAG 未配置，当前使用 AI4S demo 知识库。",
                systems=systems,
            )
        try:
            with self._client(base_url) as client:
                client.get("/health").raise_for_status()
        except Exception as exc:
            return KnowledgeHealthData(
                status="warning",
                configured=False,
                demo_available=True,
                message=f"LightRAG 不可用，当前使用 AI4S demo 知识库：{type(exc).__name__}",
                systems=systems,
            )
        return KnowledgeHealthData(
            status="ready",
            configured=True,
            demo_available=True,
            message="LightRAG 服务可用。",
            systems=systems,
        )

    def query(self, payload: KnowledgeQueryRequest) -> KnowledgeQueryResponse:
        self._ensure_known_system(payload.system_id)
        base_url = self._base_url()
        if base_url:
            try:
                return self._query_lightrag(base_url, payload)
            except Exception as exc:
                demo = self._query_demo(payload)
                return demo.model_copy(update={
                    "configured": False,
                    "message": f"LightRAG 调用失败，已返回 demo 数据：{type(exc).__name__}",
                })
        return self._query_demo(payload)

    def get_graph(self, system_id: str) -> KnowledgeGraphData:
        self._ensure_known_system(system_id)
        nodes = [KnowledgeGraphNode(**self._safe_node(item)) for item in DEMO_NODES]
        edges = [KnowledgeGraphEdge(**self._safe_edge(item)) for item in DEMO_EDGES]
        return KnowledgeGraphData(
            system_id=system_id,
            nodes=nodes,
            edges=edges,
            stats=KnowledgeGraphStats(
                entity_count=len(nodes),
                relation_count=len(edges),
                document_count=len(DEMO_DOCUMENTS),
            ),
            configured=True,
            message="AI4S demo knowledge graph.",
        )

    def get_subgraph(self, system_id: str, *, query: str | None = None, limit: int = 30) -> KnowledgeGraphData:
        graph = self.get_graph(system_id)
        limit = max(1, min(limit, 100))
        if not query:
            nodes = graph.nodes[:limit]
        else:
            tokens = self._tokenize(query)
            scored = []
            for node in graph.nodes:
                text = " ".join([node.id, node.label, node.type, " ".join(str(v) for v in node.properties.values())])
                score = self._score_text(text, tokens)
                if score > 0:
                    scored.append((score + node.score, node))
            scored.sort(key=lambda item: item[0], reverse=True)
            seed_limit = max(1, min(limit, int(limit * 0.65)))
            nodes = [node for _, node in scored[:seed_limit]]
            nodes = self._expand_with_neighbors(nodes, graph, limit)
            if not nodes:
                nodes = graph.nodes[: min(limit, 5)]
        node_ids = {node.id for node in nodes}
        edges = [edge for edge in graph.edges if edge.source in node_ids and edge.target in node_ids]
        return KnowledgeGraphData(
            system_id=system_id,
            nodes=nodes,
            edges=edges,
            stats=KnowledgeGraphStats(
                entity_count=len(nodes),
                relation_count=len(edges),
                document_count=graph.stats.document_count,
            ),
            configured=graph.configured,
            message="AI4S demo knowledge subgraph.",
        )

    @staticmethod
    def _expand_with_neighbors(
        nodes: list[KnowledgeGraphNode],
        graph: KnowledgeGraphData,
        limit: int,
    ) -> list[KnowledgeGraphNode]:
        node_by_id = {node.id: node for node in graph.nodes}
        selected: dict[str, KnowledgeGraphNode] = {node.id: node for node in nodes}
        queue = list(selected)
        for edge in graph.edges:
            if len(selected) >= limit:
                break
            source_selected = edge.source in queue
            target_selected = edge.target in queue
            if source_selected and edge.target not in selected and edge.target in node_by_id:
                selected[edge.target] = node_by_id[edge.target]
            if len(selected) >= limit:
                break
            if target_selected and edge.source not in selected and edge.source in node_by_id:
                selected[edge.source] = node_by_id[edge.source]
        return list(selected.values())[:limit]

    def _query_lightrag(self, base_url: str, payload: KnowledgeQueryRequest) -> KnowledgeQueryResponse:
        request_body = {
            "query": payload.question,
            "mode": payload.mode,
            "top_k": payload.top_k,
            "only_need_context": False,
            "include_references": True,
        }
        with self._client(base_url) as client:
            response = client.post("/query", json=request_body)
            response.raise_for_status()
            raw = response.json()
        answer = str(raw.get("response") or raw.get("answer") or raw.get("result") or "")
        hits, citations = self._normalize_lightrag_references(raw)
        graph_context = self.get_subgraph(payload.system_id, query=payload.question, limit=12) if payload.include_graph_context else None
        return KnowledgeQueryResponse(
            system_id=payload.system_id,
            question=payload.question,
            mode=payload.mode,
            answer=answer,
            hits=hits[: payload.top_k],
            citations=citations[: payload.top_k],
            graph_context=graph_context,
            configured=True,
            message="LightRAG query completed.",
        )

    def _query_demo(self, payload: KnowledgeQueryRequest) -> KnowledgeQueryResponse:
        tokens = self._tokenize(payload.question)
        scored = []
        for doc in DEMO_DOCUMENTS:
            text = " ".join([
                str(doc.get("title", "")),
                str(doc.get("summary", "")),
                " ".join(str(item) for item in doc.get("keywords", [])),
            ])
            score = self._score_text(text, tokens)
            if score > 0:
                scored.append((score, doc))
        if not scored:
            scored = [(0.1, doc) for doc in DEMO_DOCUMENTS]
        scored.sort(key=lambda item: item[0], reverse=True)
        selected = scored[: payload.top_k]
        hits = [
            KnowledgeHit(
                source_id=doc["source_id"],
                title=doc["title"],
                snippet=doc["summary"],
                source=doc.get("source"),
                doi=doc.get("doi"),
                url=doc.get("url"),
                journal=doc.get("metadata", {}).get("journal"),
                year=doc.get("metadata", {}).get("year"),
                authors=list(doc.get("metadata", {}).get("authors", [])),
                score=round(float(score), 4),
                metadata=self._safe_metadata(doc.get("metadata", {})),
            )
            for score, doc in selected
        ]
        citations = [
            KnowledgeCitation(
                source_id=doc["source_id"],
                title=doc["title"],
                doi=doc.get("doi"),
                url=doc.get("url"),
                journal=doc.get("metadata", {}).get("journal"),
                year=doc.get("metadata", {}).get("year"),
                authors=list(doc.get("metadata", {}).get("authors", [])),
                chunk_id=f"{doc['source_id']}#summary",
            )
            for _, doc in selected
        ]
        graph_context = self.get_subgraph(payload.system_id, query=payload.question, limit=12) if payload.include_graph_context else None
        answer = self._build_demo_answer(payload.question, selected)
        return KnowledgeQueryResponse(
            system_id=payload.system_id,
            question=payload.question,
            mode=payload.mode,
            answer=answer,
            hits=hits,
            citations=citations,
            graph_context=graph_context,
            configured=False,
            message="LightRAG 未配置，返回 AI4S demo 知识库结果。",
        )

    def _normalize_lightrag_references(self, raw: dict[str, Any]) -> tuple[list[KnowledgeHit], list[KnowledgeCitation]]:
        references = raw.get("references") or raw.get("sources") or raw.get("context") or []
        if isinstance(references, dict):
            references = references.get("chunks") or references.get("items") or []
        if not isinstance(references, list):
            references = []
        hits: list[KnowledgeHit] = []
        citations: list[KnowledgeCitation] = []
        for idx, item in enumerate(references):
            if not isinstance(item, dict):
                continue
            source_id = str(item.get("reference_id") or item.get("source_id") or item.get("id") or f"lightrag_ref_{idx + 1}")
            title = str(item.get("title") or item.get("file_path") or item.get("source") or source_id)
            snippet = str(item.get("content") or item.get("snippet") or item.get("text") or "")[:500]
            source = str(item.get("file_path") or item.get("source") or item.get("url") or "") or None
            metadata = self._safe_metadata(item.get("metadata", {}))
            hits.append(KnowledgeHit(
                source_id=source_id,
                title=title,
                snippet=snippet,
                source=source,
                doi=item.get("doi") or metadata.get("doi"),
                url=item.get("url") or metadata.get("url"),
                journal=item.get("journal") or metadata.get("journal"),
                year=item.get("year") or metadata.get("year"),
                authors=list(item.get("authors") or metadata.get("authors") or []),
                score=float(item.get("score") or item.get("similarity") or 0.0),
                metadata=metadata,
            ))
            citations.append(KnowledgeCitation(
                source_id=source_id,
                title=title,
                doi=item.get("doi") or metadata.get("doi"),
                url=item.get("url") or metadata.get("url"),
                journal=item.get("journal") or metadata.get("journal"),
                year=item.get("year") or metadata.get("year"),
                authors=list(item.get("authors") or metadata.get("authors") or []),
                chunk_id=item.get("chunk_id") or source_id,
            ))
        return hits, citations

    @staticmethod
    def _build_demo_answer(question: str, selected: list[tuple[float, dict[str, Any]]]) -> str:
        papers = [doc for _, doc in selected if doc.get("metadata", {}).get("source_type") == "paper_seed"]
        linked = []
        for doc in papers[:4]:
            metadata = doc.get("metadata", {})
            year = metadata.get("year")
            journal = metadata.get("journal") or doc.get("source") or "paper"
            linked.append(f"[{doc['title']}]({doc.get('url') or f'https://doi.org/{doc.get('doi')}'}) ({journal}, {year})")
        references = "\n".join(f"- {item}" for item in linked) or "- 当前命中主要来自内置 demo card，建议接入 LightRAG 后补充全文证据。"
        return (
            "### 结论\n"
            "氟聚合物/PVDF 体系的介电与热稳定性优化应同时控制极化能力、击穿强度、损耗和高温载流子传输。"
            "RAG 命中的论文更支持组合策略：以 PVDF 或含氟共聚物为基体，叠加界面工程、合理纳米填料、多层结构、交联或全有机分子设计，并用 AI4S 描述符/机器学习做候选筛选。\n\n"
            "### 设计要点\n"
            "- 介电提升不能只追求高介电常数；需要同步约束击穿强度、介电损耗和充放电效率。\n"
            "- 高温场景优先关注载流子陷阱、交联结构、全有机耐热骨架和薄膜尺度工艺。\n"
            "- 对 PVDF、PVDF-HFP、P(VDF-TrFE-CTFE) 等氟聚合物，结构证据应绑定单体组成、加工形貌和测试条件。\n"
            "- AI4S 流程适合把论文中的结构策略转为特征、约束和候选生成规则，而不是直接把单篇论文结论外推。\n\n"
            "### 相关论文\n"
            f"{references}\n\n"
            "### 查询解释\n"
            f"你的问题是：{question}。当前回答来自 DOI 可追溯的 demo seed；正式生产结果应以 LightRAG ingestion 后的全文 chunks 和图谱证据为准。"
        )

    @staticmethod
    def _base_url() -> str:
        return os.getenv("KNOWLEDGE_RAG_BASE_URL", "").strip().rstrip("/")

    @staticmethod
    def _client(base_url: str) -> httpx.Client:
        headers = {}
        api_key = os.getenv("KNOWLEDGE_RAG_API_KEY", "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return httpx.Client(base_url=base_url, headers=headers, timeout=30.0)

    @staticmethod
    def _ensure_known_system(system_id: str) -> None:
        if system_id != DEMO_SYSTEM_ID:
            raise HTTPException(status_code=404, detail=f"知识库体系 '{system_id}' 不存在")

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        normalized = text.lower()
        for char in ",.;:/()[]{}|_-+?？!！":
            normalized = normalized.replace(char, " ")
        tokens = {token for token in normalized.split() if len(token) >= 2}
        synonym_rules = {
            "氟": ["fluoropolymer", "pvdf", "fluorinated"],
            "聚合物": ["polymer"],
            "介电": ["dielectric", "dielectrics"],
            "储能": ["energy", "storage", "capacitive"],
            "热": ["thermal", "temperature", "high-temperature"],
            "高温": ["thermal", "temperature", "high-temperature"],
            "稳定": ["stability", "thermal_stability"],
            "机器学习": ["machine", "learning", "ai4s"],
            "图谱": ["graph", "knowledge"],
            "击穿": ["breakdown"],
            "损耗": ["loss"],
            "交联": ["crosslinked", "crosslinking"],
            "多层": ["multilayer"],
            "填料": ["filler", "nanofiller"],
        }
        for marker, expansions in synonym_rules.items():
            if marker in normalized:
                tokens.update(expansions)
        return tokens

    @staticmethod
    def _score_text(text: str, tokens: set[str]) -> float:
        lower = text.lower()
        return float(sum(1 for token in tokens if token in lower))

    @staticmethod
    def _safe_metadata(value: Any) -> dict:
        if not isinstance(value, dict):
            return {}
        blocked = {"storage_uri", "api_key", "token", "secret", "password", "index_path"}
        return {str(key): val for key, val in value.items() if str(key).lower() not in blocked}

    def _safe_node(self, value: dict[str, Any]) -> dict[str, Any]:
        item = dict(value)
        item["properties"] = self._safe_metadata(item.get("properties", {}))
        return item

    def _safe_edge(self, value: dict[str, Any]) -> dict[str, Any]:
        item = dict(value)
        item["properties"] = self._safe_metadata(item.get("properties", {}))
        return item
