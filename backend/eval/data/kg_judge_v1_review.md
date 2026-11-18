# Relationship judge evaluation set v1: label review

Draft labels were proposed by Claude and are **not verified**. For each candidate, decide whether the **quote**, read with its **context sentence**, says that *this paper itself* states the relationship in the direction shown:

- `stated`: yes.
- `not_stated`: the entities only appear together, or the quote states a different relationship, the other direction, or something that needs an inference.
- `other_work`: the quote states it, but about cited or earlier studies, a cited report, or general background.

Record decisions in `kg_judge_v1_labels.csv`: `verified_label` = `ok` (agree) or the correct label, plus `verified_by`. Optionally fix `verified_borderline` (`yes`/`no`) and add a `comment`. Then run `uv run python -m scripts.kg_judge_labels apply`.

Relationship meanings: `uses`: the source method uses or builds on the target; `evaluated_on`: the source method is evaluated, trained, or tested on the target dataset; `measured_by`: the source's performance or result is measured with the target metric; `addresses`: the source method is applied to or solves the target task; `compared_with`: the paper compares the two methods; `reports`: the paper reports the target finding about the source.

## Clear cases (26)

### kgj-001: reports

- **Paper:** Engineering Polymeric Hydrogels, Nanogels, and Microgels for Next-Generation Tissue Regeneration: Materials, Mechanisms, and Translational Perspectives (biomaterials), section *Detailed Synthetic Approaches of Hydrogel, Nanogel, and Microgel*
- **Relationship:** 3D bioprinting approach utilizing crosslinkable microgels (method) —reports→ a 3D bioprinting approach utilizing crosslinkable microgels can enhance mechanical stability and induce spontaneous microvascular networks. (finding)
- **Context sentence** (same passage): utilized injectable microgel systems to create 3D constructs in vivo, allowing cell proliferation and extracellular matrix (ECM) deposition ( _Griffin et al._ ).<sup>29</sup> Furthermore, 3D bioprinted scaffolds were developed using microgel inks, achieving hierarchical organization mimicking natural tissues.<sup>55</sup>
- **Quote:** > In this study, the authors introduced a 3D bioprinting approach utilizing crosslinkable microgels to enhance mechanical stability and induce spontaneous microvascular networks composed of human umbilical cord vein endothelial cells (HUVECs) within a soft gelatin methacryloyl (GelMA)-based bioink.
- **Draft label:** `other_work` (cited_study), kept by a model run
- **Why:** Review: 'the authors introduced' describes another study.

### kgj-002: addresses

- **Paper:** Research on Algorithmic Trading and Its Role in Pricing Efficiency in Chinese Stock Market (finance), section *1. Introduction*
- **Relationship:** regression model (method) —addresses→ investigate the relationship between stock pricing efficiency and algorithm trading system (task)
- **Context sentence** (same passage): To further improve the trading system, our study focused on the adjusting speed of prices based on market variation and how well the share prices reflect available information.
- **Quote:** > In this paper, a regression model was built to investigate the relationship between stock pricing efficiency and algorithm trading system.
- **Draft label:** `stated` (stated), kept by a model run
- **Why:** 'In this paper, a regression model was built to investigate ...'

### kgj-003: addresses

- **Paper:** Vision Based Game Development Using Human Computer Interaction (computer science), section *Vision Based Game Development Using Human Computer Interaction*
- **Relationship:** vision-based system (method) —addresses→ detection of long voluntary eye blinks and interpretation of blink patterns for communication between man and machine (task)
- **Context sentence** (same passage): Ms.S.Sumathi Dr.S.K.Srivatsa Dr.M.Uma Maheswari Bharath University St.Joseph College of Engineering Bharath University Chennai,India Chennai,India Chennai,India **_Abstract_ — A Human Computer Interface (HCI) System for playing games is designed here for more natural communication with the machines.
- **Quote:** > The system presented here is a vision-based system for detection of long voluntary eye blinks and interpretation of blink patterns for communication between man and machine.
- **Draft label:** `stated` (stated), kept by a model run
- **Why:** 'The system presented here is a vision-based system for detection of ...'

### kgj-005: uses

- **Paper:** Vision Based Game Development Using Human Computer Interaction (computer science), section *Face Detection*
- **Relationship:** real-time face detection algorithm (method) —uses→ Six-Segmented Rectangular (SSR) filter (tool)
- **Context sentence** (previous passage): This system design can be broken down into three modules, (1) Facial Features tracking (2) Integrating Nose tip movements with the mouse cursor (3) Replacing the eye blinks with the mouse click events.
- **Quote:** > In this module, we propose a real-time face detection algorithm using Six-Segmented Rectangular (SSR) filter, distance information, and template matching technique.
- **Draft label:** `stated` (stated), kept by a model run
- **Why:** 'we propose a real-time face detection algorithm using SSR filter'

### kgj-006: uses

- **Paper:** Vision Based Game Development Using Human Computer Interaction (computer science), section *Face Detection*
- **Relationship:** real-time face detection algorithm (method) —uses→ template matching technique (method)
- **Context sentence** (previous passage): This system design can be broken down into three modules, (1) Facial Features tracking (2) Integrating Nose tip movements with the mouse cursor (3) Replacing the eye blinks with the mouse click events.
- **Quote:** > In this module, we propose a real-time face detection algorithm using Six-Segmented Rectangular (SSR) filter, distance information, and template matching technique.
- **Draft label:** `stated` (stated), kept by a model run
- **Why:** Same sentence: '... and template matching technique'.

### kgj-007: uses

- **Paper:** Vision Based Game Development Using Human Computer Interaction (computer science), section *Blink Detection*
- **Relationship:** blink detection (method) —uses→ eye's ROI (concept)
- **Context sentence** (previous passage): To detect motion in a certain region we subtract the pixels in that region from the same pixels of the previous frame, and at a given location (x,y); if the absolute value of the subtraction was larger than a certain threshold, we consider a motion at that pixel.
- **Quote:** > We apply blink detection in the eye’s ROI before finding the eye’s new exact location.
- **Draft label:** `stated` (stated), kept by a model run
- **Why:** 'We apply blink detection in the eye's ROI'

### kgj-008: uses

- **Paper:** Vision Based Game Development Using Human Computer Interaction (computer science), section *Blink Detection*
- **Relationship:** motion detection (method) —uses→ eye's ROI (concept)
- **Context sentence** (same passage): The blink detection process is run only if the eye is not moving, because when a person uses the mouse and wants to click, he moves the pointer to the desired location, stops, and then clicks, so basically the same for using the face, the user moves the pointer with the tip of the nose, stops, then blinks.
- **Quote:** > To detect a blink we apply motion detection in the eye’s ROI
- **Draft label:** `stated` (stated), kept by a model run
- **Why:** 'To detect a blink we apply motion detection in the eye's ROI'

### kgj-009: reports

- **Paper:** Engineering Polymeric Hydrogels, Nanogels, and Microgels for Next-Generation Tissue Regeneration: Materials, Mechanisms, and Translational Perspectives (biomaterials), section *Broad Future Perspectives*
- **Relationship:** predict the mechanical and swelling properties of hydrogels (task) —reports→ machine learning models have been developed to predict the mechanical and swelling properties of hydrogels based on monomer composition. (finding)
- **Context sentence** (same passage): In this regard,
- **Quote:** > machine learning models have been developed to predict the mechanical and swelling properties of hydrogels based on monomer composition.
- **Draft label:** `other_work` (background), kept by a model run
- **Why:** Review's future-perspectives section: 'models have been developed'.

### kgj-011: uses

- **Paper:** Research on Algorithmic Trading and Its Role in Pricing Efficiency in Chinese Stock Market (finance), section *1. Introduction*
- **Relationship:** mediation effect analysis (method) —uses→ pricing efficiency (concept)
- **Context sentence** (same passage): Wang took the A-share market data from 2016 to 2021 as a sample and found that algorithmic trading has significantly improved the pricing efficiency of my country's stock market.
- **Quote:** > It is also concluded through the mediation effect analysis that algorithmic trading mainly improves the stock market pricing efficiency by slowing down market volatility and investor belief heterogeneity.
- **Draft label:** `other_work` (cited_study), kept by a model run
- **Why:** Context: 'Wang took the A-share market data ... and found'.

### kgj-012: uses

- **Paper:** Geometric Signatures of Switching Behavior in Mechanobiology (mathematical modelling), section *Geometric Signatures of Switching Behavior in Mechanobiology*
- **Relationship:** switch points (concept) —uses→ singularities in the flow field (concept)
- **Context sentence** (same passage): Are there features of free energy landscapes that indicate a switch?
- **Quote:** > We discover geometric signatures of catch-slip and pathway switching behavior in the form of singularities in the flow field that describes force-induced deformation of minimum and saddle points. These singularities, which we call “switch points”, can be viewed as the basic building blocks of force-induced switching behavior in two dimensional systems.
- **Draft label:** `not_stated` (wrong_relation), kept by a model run
- **Why:** Switch points appear as singularities; nothing uses anything.

### kgj-013: reports

- **Paper:** Geometric Signatures of Switching Behavior in Mechanobiology (mathematical modelling), section *Geometric Signatures of Switching Behavior in Mechanobiology*
- **Relationship:** switch points (concept) —reports→ Switch points provide a unified view of known switching mechanisms, and we show how established catch bond models can be understood using switch points. (finding)
- **Context sentence** (same passage): In higher dimensions, the generalization of switch points indicate other, more exotic, responses to force.
- **Quote:** > Switch points provide a unified view of known switching mechanisms, and we show how established catch bond models can be understood using switch points.
- **Draft label:** `stated` (stated), kept by a model run
- **Why:** 'Switch points provide a unified view ... and we show ...'

### kgj-017: reports

- **Paper:** Research on Algorithmic Trading and Its Role in Pricing Efficiency in Chinese Stock Market (finance), section *Research on Algorithmic Trading and Its Role in Pricing Efficiency in Chinese Stock Market*
- **Relationship:** algorithmic trading (method) —reports→ algorithmic trading can effectively improve the pricing efficiency of Chinese stock market (finding)
- **Context sentence** (same passage): Combining with the current market transaction structure and institutional characteristics in China, this study uses the proportion of small transaction volume STR as a proxy variable to measure the intensity of algorithmic trading activities in China.
- **Quote:** > Empirical results show that algorithmic trading can effectively improve the pricing efficiency of Chinese stock market.
- **Draft label:** `stated` (stated), kept by a model run
- **Why:** Abstract: 'Empirical results show that ...'

### kgj-018: reports

- **Paper:** Research on Algorithmic Trading and Its Role in Pricing Efficiency in Chinese Stock Market (finance), section *1. Introduction*
- **Relationship:** mediation effect analysis (method) —reports→ algorithmic trading improves pricing efficiency by slowing market volatility and investor belief heterogeneity (finding)
- **Context sentence** (same passage): Wang took the A-share market data from 2016 to 2021 as a sample and found that algorithmic trading has significantly improved the pricing efficiency of my country's stock market.
- **Quote:** > It is also concluded through the mediation effect analysis that algorithmic trading mainly improves the stock market pricing efficiency by slowing down market volatility and investor belief heterogeneity.
- **Draft label:** `other_work` (cited_study), kept by a model run
- **Why:** Context: Wang's study.

### kgj-019: uses

- **Paper:** Research on Algorithmic Trading and Its Role in Pricing Efficiency in Chinese Stock Market (finance), section *1. Introduction*
- **Relationship:** mediation effect analysis (method) —uses→ Algorithmic Trading (method)
- **Context sentence** (same passage): Wang took the A-share market data from 2016 to 2021 as a sample and found that algorithmic trading has significantly improved the pricing efficiency of my country's stock market.
- **Quote:** > It is also concluded through the mediation effect analysis that algorithmic trading mainly improves the stock market pricing efficiency by slowing down market volatility and investor belief heterogeneity.
- **Draft label:** `other_work` (cited_study), kept by a model run
- **Why:** Context: Wang's study; also 'uses' is not what the quote says.

### kgj-020: addresses

- **Paper:** Research on Algorithmic Trading and Its Role in Pricing Efficiency in Chinese Stock Market (finance), section *4. Conclusion*
- **Relationship:** algorithmic trading (method) —addresses→ pricing efficiency (task)
- **Context sentence** (same passage): The empirical results show that
- **Quote:** > algorithmic trading can effectively improve the pricing efficiency of my country's stock market.
- **Draft label:** `not_stated` (wrong_relation), kept by a model run
- **Why:** Own result, but 'improves' is not 'addresses'.

### kgj-021: reports

- **Paper:** Research on Algorithmic Trading and Its Role in Pricing Efficiency in Chinese Stock Market (finance), section *4. Conclusion*
- **Relationship:** algorithmic trading (method) —reports→ algorithmic trading improves pricing efficiency (finding)
- **Context sentence** (same passage): The empirical results show that
- **Quote:** > algorithmic trading can effectively improve the pricing efficiency of my country's stock market.
- **Draft label:** `stated` (stated), kept by a model run
- **Why:** Conclusion: 'The empirical results show that ...'

### kgj-022: compared_with

- **Paper:** Research on Algorithmic Trading and Its Role in Pricing Efficiency in Chinese Stock Market (finance), section *4. Conclusion*
- **Relationship:** AI strategies (method) —compared_with→ other hedge fund strategies (method)
- **Context sentence** (same passage): After research and comparison, the report found that
- **Quote:** > AI strategies outperformed other hedge fund strategies in the long term, with the highest annualized rate and Sharpe ratio.
- **Draft label:** `other_work` (cited_study), kept by a model run
- **Why:** Context: 'the report found that'.

### kgj-023: reports

- **Paper:** Research on Algorithmic Trading and Its Role in Pricing Efficiency in Chinese Stock Market (finance), section *4. Conclusion*
- **Relationship:** AI strategies (method) —reports→ AI strategies outperformed other hedge fund strategies in the long term (finding)
- **Context sentence** (same passage): After research and comparison, the report found that
- **Quote:** > AI strategies outperformed other hedge fund strategies in the long term, with the highest annualized rate and Sharpe ratio.
- **Draft label:** `other_work` (cited_study), kept by a model run
- **Why:** Context: 'the report found that'.

### kgj-024: addresses

- **Paper:** Vision Based Game Development Using Human Computer Interaction (computer science), section *Vision Based Game Development Using Human Computer Interaction*
- **Relationship:** Human Computer Interface (HCI) System (method) —addresses→ playing games (task)
- **Context sentence** (same passage): Ms.S.Sumathi Dr.S.K.Srivatsa Dr.M.Uma Maheswari Bharath University St.Joseph College of Engineering Bharath University Chennai,India Chennai,India Chennai,India **_Abstract_ —
- **Quote:** > A Human Computer Interface (HCI) System for playing games is designed here
- **Draft label:** `stated` (stated), kept by a model run
- **Why:** 'A Human Computer Interface (HCI) System for playing games is designed here'

### kgj-025: compared_with

- **Paper:** Vision Based Game Development Using Human Computer Interaction (computer science), section *Face Detection*
- **Relationship:** real-time face detection algorithm (method) —compared_with→ template matching technique (method)
- **Context sentence** (previous passage): This system design can be broken down into three modules, (1) Facial Features tracking (2) Integrating Nose tip movements with the mouse cursor (3) Replacing the eye blinks with the mouse click events.
- **Quote:** > In this module, we propose a real-time face detection algorithm using Six-Segmented Rectangular (SSR) filter, distance information, and template matching technique.
- **Draft label:** `not_stated` (wrong_relation), constructed from a real quote
- **Why:** The algorithm uses template matching; no comparison.

### kgj-026: compared_with

- **Paper:** Vision Based Game Development Using Human Computer Interaction (computer science), section *Face Detection*
- **Relationship:** Six-Segmented Rectangular (SSR) filter (method) —compared_with→ template matching technique (method)
- **Context sentence** (previous passage): This system design can be broken down into three modules, (1) Facial Features tracking (2) Integrating Nose tip movements with the mouse cursor (3) Replacing the eye blinks with the mouse click events.
- **Quote:** > In this module, we propose a real-time face detection algorithm using Six-Segmented Rectangular (SSR) filter, distance information, and template matching technique.
- **Draft label:** `not_stated` (co_mention), constructed from a real quote
- **Why:** Listed together; not compared.

### kgj-027: uses

- **Paper:** Vision Based Game Development Using Human Computer Interaction (computer science), section *Face Detection*
- **Relationship:** Six-Segmented Rectangular (SSR) filter (method) —uses→ real-time face detection algorithm (method)
- **Context sentence** (previous passage): This system design can be broken down into three modules, (1) Facial Features tracking (2) Integrating Nose tip movements with the mouse cursor (3) Replacing the eye blinks with the mouse click events.
- **Quote:** > In this module, we propose a real-time face detection algorithm using Six-Segmented Rectangular (SSR) filter, distance information, and template matching technique.
- **Draft label:** `not_stated` (wrong_direction), constructed from a real quote
- **Why:** Reversed: the algorithm uses the filter.

### kgj-028: uses

- **Paper:** Vision Based Game Development Using Human Computer Interaction (computer science), section *Face Detection*
- **Relationship:** template matching technique (method) —uses→ real-time face detection algorithm (method)
- **Context sentence** (previous passage): This system design can be broken down into three modules, (1) Facial Features tracking (2) Integrating Nose tip movements with the mouse cursor (3) Replacing the eye blinks with the mouse click events.
- **Quote:** > In this module, we propose a real-time face detection algorithm using Six-Segmented Rectangular (SSR) filter, distance information, and template matching technique.
- **Draft label:** `not_stated` (wrong_direction), constructed from a real quote
- **Why:** Reversed.

### kgj-029: measured_by

- **Paper:** Research on Algorithmic Trading and Its Role in Pricing Efficiency in Chinese Stock Market (finance), section *4. Conclusion*
- **Relationship:** AI strategies (method) —measured_by→ Sharpe ratio (metric)
- **Context sentence** (same passage): After research and comparison, the report found that
- **Quote:** > AI strategies outperformed other hedge fund strategies in the long term, with the highest annualized rate and Sharpe ratio.
- **Draft label:** `other_work` (cited_study), constructed from a real quote
- **Why:** Stated with 'Sharpe ratio', but by the cited report.

### kgj-030: reports

- **Paper:** Vision Based Game Development Using Human Computer Interaction (computer science), section *Vision Based Game Development Using Human Computer Interaction*
- **Relationship:** vision-based system (method) —reports→ Blink patterns make games more immersive. (finding)
- **Context sentence** (same passage): Ms.S.Sumathi Dr.S.K.Srivatsa Dr.M.Uma Maheswari Bharath University St.Joseph College of Engineering Bharath University Chennai,India Chennai,India Chennai,India **_Abstract_ — A Human Computer Interface (HCI) System for playing games is designed here for more natural communication with the machines.
- **Quote:** > The system presented here is a vision-based system for detection of long voluntary eye blinks and interpretation of blink patterns for communication between man and machine.
- **Draft label:** `not_stated` (inferred), constructed from a real quote
- **Why:** Not in the quote.

### kgj-031: evaluated_on

- **Paper:** Research on Algorithmic Trading and Its Role in Pricing Efficiency in Chinese Stock Market (finance), section *4. Conclusion*
- **Relationship:** algorithmic trading (method) —evaluated_on→ Chinese stock market (dataset)
- **Context sentence** (same passage): The empirical results show that
- **Quote:** > algorithmic trading can effectively improve the pricing efficiency of my country's stock market.
- **Draft label:** `not_stated` (wrong_relation), constructed from a real quote
- **Why:** Own result about an effect, not an evaluation on a dataset.

## Borderline cases (scored separately) (5)

### kgj-004: reports

- **Paper:** Vision Based Game Development Using Human Computer Interaction (computer science), section *I. INTRODUCTION*
- **Relationship:** eye tracker (tool) —reports→ using an eye tracker can increase the immersion and leads to a stronger feeling of being part of the game (finding)
- **Context sentence** (same passage): This system can be used in playing games like first shooter game, a role playing game and an action game.
- **Quote:** > When we compare eye-based and mouse-based control it is found that using an eye tracker can increase the immersion and leads to a stronger feeling of being part of the game.
- **Draft label:** `stated` (stated), kept by a model run
- **Why:** 'When we compare ... it is found that' in the Introduction: own comparison or prior result?

### kgj-010: addresses

- **Paper:** Research on Algorithmic Trading and Its Role in Pricing Efficiency in Chinese Stock Market (finance), section *1. Introduction*
- **Relationship:** regression model (method) —addresses→ pricing efficiency (task)
- **Context sentence** (same passage): To further improve the trading system, our study focused on the adjusting speed of prices based on market variation and how well the share prices reflect available information.
- **Quote:** > In this paper, a regression model was built to investigate the relationship between stock pricing efficiency and algorithm trading system.
- **Draft label:** `not_stated` (inferred), kept by a model run
- **Why:** The model investigates a relationship involving pricing efficiency; it does not address pricing efficiency itself.

### kgj-014: uses

- **Paper:** Geometric Signatures of Switching Behavior in Mechanobiology (mathematical modelling), section *Geometric Signatures of Switching Behavior in Mechanobiology*
- **Relationship:** framework of switch points and switch lines (method) —uses→ switch points (concept)
- **Context sentence** (same passage): To third order in _V_ ( **_x_** ), switch lines are straight lines, and equations for their direction are given in the SM.
- **Quote:** > The framework of switch points and switch lines reveals behaviors that would otherwise be ‘invisible’ from viewing the free energy landscape at any particular force.
- **Draft label:** `not_stated` (inferred), kept by a model run
- **Why:** The framework consists of switch points; 'uses' is not stated.

### kgj-015: addresses

- **Paper:** Geometric Signatures of Switching Behavior in Mechanobiology (mathematical modelling), section *Geometric Signatures of Switching Behavior in Mechanobiology*
- **Relationship:** geometric framework of switch points and switch lines (method) —addresses→ catch-slip bond (task)
- **Context sentence** (same passage): _Application to P-Selectin_ —
- **Quote:** > To illustrate the utility of the geometric framework of switch points and switch lines, we develop a model of the catch-slip bond between P-Selectin and its glycoprotein ligand-1 (PSGL-1).
- **Draft label:** `stated` (stated), kept by a model run
- **Why:** 'To illustrate the utility of the framework ..., we develop a model of catch-slip bond'; catch-slip bond as a task is loose.

### kgj-016: uses

- **Paper:** Vision Based Game Development Using Human Computer Interaction (computer science), section *Face Detection*
- **Relationship:** SSR filter (method) —uses→ Between-the-Eyes (concept)
- **Context sentence** (same passage): 1, 2010_ we propose the method combine both feature-based and image-based approach to detect the point between the eyes by using Six-Segmented Rectangular filter (SSR filter).
- **Quote:** > The proposed SSR filter, which is the rectangle divided into 6 segments, operates by using the concept of brightdark relation around Between-the-Eyes area.
- **Draft label:** `stated` (stated), kept by a model run
- **Why:** 'The proposed SSR filter ... operates by using the concept of ... Between-the-Eyes'; context cites a 2010 method.
