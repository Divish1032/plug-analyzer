# Research and Technical References

**Review date:** 14 August 2026  
Primary papers and official project/vendor documentation were preferred. A cited method is not automatically appropriate for this dataset; the candidate protocol explains where a source supports a principle versus where engineering judgment is still required.

## Antiperspirant plug mechanism and microfluidic model

1. Sakhawoth Y. et al. “Real time observation of the interaction between aluminium salts and sweat under microfluidic conditions.” *Scientific Reports* 11, 6376 (2021). [DOI](https://doi.org/10.1038/s41598-021-85691-8) / [open full text](https://pmc.ncbi.nlm.nih.gov/articles/PMC7973555/)
   - Directly relevant T-junction sweat-channel model; FITC-BSA confocal stacks; wall-first aggregate growth; reduced but positive residual flow.
2. Bretagne A. et al. “The mechanism of eccrine sweat pore plugging by aluminium salts using microfluidics combined with small angle X-ray scattering.” *Soft Matter* 13 (2017). [DOI](https://doi.org/10.1039/C6SM02510B) / [PubMed](https://pubmed.ncbi.nlm.nih.gov/28485735/)
   - Supports wall-bound nucleation followed by aggregate growth and pore occlusion.

## Quantitative fluorescence and reproducibility

3. Waters J.C. “Accuracy and precision in quantitative fluorescence microscopy.” *Journal of Cell Biology* 185 (2009). [DOI](https://doi.org/10.1083/jcb.200903097) / [open full text](https://pmc.ncbi.nlm.nih.gov/articles/PMC2712964/)
   - Raw linear data, background, SNR, saturation, and photobleaching considerations.
4. Jonkman J. et al. “Tutorial: guidance for quantitative confocal microscopy.” *Nature Protocols* 15 (2020). [DOI](https://doi.org/10.1038/s41596-020-0313-9)
5. Montero Llopis P. et al. “Best practices and tools for reporting reproducible fluorescence microscopy methods.” *Nature Methods* 18 (2021). [DOI](https://doi.org/10.1038/s41592-021-01156-w)
6. Peng T. et al. “A BaSiC tool for background and shading correction of optical microscopy images.” *Nature Communications* 8 (2017). [DOI](https://doi.org/10.1038/ncomms14836)
   - Supports additive/multiplicative shading modelling; a static foreground can contaminate an inferred flat field, so v1 does not estimate one from the plug stack itself.
7. Otsu N. “A threshold selection method from gray-level histograms.” *IEEE Transactions on Systems, Man, and Cybernetics* 9 (1979). [DOI](https://doi.org/10.1109/TSMC.1979.4310076)
   - Development baseline only; not evidence of a universal plug threshold.
8. Diehl H., Markuszewski R. “Studies on fluorescein—VII: The fluorescence of fluorescein as a function of pH.” *Talanta* 36 (1989). [DOI](https://doi.org/10.1016/0039-9140%2889%2980213-9)
   - Supports the pH warning if the fluorophore is FITC/fluorescein.
9. Yoo H. et al. “Measurement and analysis of the point spread function of confocal microscopy.” *Journal of Microscopy* (2006). [DOI](https://doi.org/10.1111/j.1365-2818.2006.01556.x)
10. Hell S. et al. “Aberrations in confocal fluorescence microscopy induced by mismatches in refractive index.” *Journal of Microscopy* (1993). [DOI](https://doi.org/10.1111/j.1365-2818.1993.tb03315.x)
11. Diel E.E. et al. “Tutorial: avoiding and correcting sample-induced spherical aberration artifacts in 3D fluorescence microscopy.” *Nature Protocols* (2020). [DOI](https://doi.org/10.1038/s41596-020-0360-2)

## Method comparison and segmentation validation

12. Bland J.M., Altman D.G. “Statistical methods for assessing agreement between two methods of clinical measurement.” *The Lancet* (1986). [PubMed](https://pubmed.ncbi.nlm.nih.gov/2868172/) / [DOI](https://doi.org/10.1016/S0140-6736%2886%2990837-8)
   - Agreement, not correlation alone.
13. Lin L.I. “A concordance correlation coefficient to evaluate reproducibility.” *Biometrics* (1989). [DOI](https://doi.org/10.2307/2532051)
14. Taha A.A., Hanbury A. “Metrics for evaluating 3D medical image segmentation.” *BMC Medical Imaging* 15 (2015). [DOI](https://doi.org/10.1186/s12880-015-0068-x)
15. Zou K.H. et al. “Statistical validation of image segmentation quality based on a spatial overlap index.” *Academic Radiology* 11 (2004). [PubMed](https://pubmed.ncbi.nlm.nih.gov/14974593/) / [DOI](https://doi.org/10.1016/S1076-6332%2803%2900671-8)
16. Sensakovic W.F. et al. “Influence of segmentation on computer-aided diagnosis.” *Medical Physics* (2010). [DOI](https://doi.org/10.1118/1.3392287)

## Nikon and microscopy file formats

17. Nikon AX software overview. [Nikon](https://www.microscope.healthcare.nikon.com/products/confocal-microscopes/ax/software)
18. Nikon NIS-Elements software information. [Nikon](https://www.microscope.healthcare.nikon.com/products/software/nis-elements/software-resources)
19. `nd2` Python reader: modern/legacy ND2, metadata, Dask/xarray access. [GitHub](https://github.com/tlambert03/nd2) / [API docs](https://tlambert03.github.io/nd2/)
20. Bio-Formats Nikon ND2 support. [OME documentation](https://bio-formats.readthedocs.io/en/latest/formats/nikon-nis-elements-nd2.html)
21. Bio-Formats licensing. [OME](https://www.openmicroscopy.org/licensing/)
22. OME data model. [OME documentation](https://docs.openmicroscopy.org/ome-model/6.2/)
23. BioIO reader architecture and lazy image access. [BioIO documentation](https://bioio-devs.github.io/bioio/)

## Large-file processing and local storage

24. `tifffile`: TIFF, BigTIFF, ImageJ, OME-TIFF, memory mapping, and Zarr interfaces. [Official repository](https://github.com/cgohlke/tifffile)
25. Dask array chunks. [Official documentation](https://docs.dask.org/en/latest/array-chunks.html)
26. Dask array best practices. [Official documentation](https://docs.dask.org/en/latest/array-best-practices.html)
27. Dask local scheduling. [Official documentation](https://docs.dask.org/en/stable/scheduling.html)
28. Zarr arrays and chunked local storage. [Official documentation](https://zarr.readthedocs.io/en/stable/user-guide/arrays/)
29. OME-Zarr/NGFF specification. [OME specification](https://ngff.openmicroscopy.org/0.5/)
30. `psutil` system and process resource information. [Official documentation](https://psutil.readthedocs.io/stable/)
31. SQLite as a serverless, single-file application database. [Serverless](https://www.sqlite.org/serverless.html) / [single-file format](https://www.sqlite.org/onefile.html) / [atomic commit](https://www.sqlite.org/atomiccommit.html)

## Desktop process and packaging

32. Qt `QProcess` for asynchronous worker processes. [Qt for Python](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QProcess.html)
33. Qt standard application/configuration paths. [Qt for Python](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QStandardPaths.html)
34. `pyside6-deploy`, Qt's Nuitka-based deployment tool. [Qt for Python](https://doc.qt.io/qtforpython-6/deployment/deployment-pyside6-deploy.html)
35. PyQtGraph `ImageView` and ROI APIs. [ImageView](https://pyqtgraph.readthedocs.io/en/latest/api_reference/widgets/imageview.html) / [ROI](https://pyqtgraph.readthedocs.io/en/latest/api_reference/graphicsItems/roi.html)

## Evidence gaps still requiring real laboratory data

- Untouched Nikon AX file(s) and the exact NIS-Elements version.
- Label/fluorophore identity and acquisition settings for `test.tif`.
- Pre-contact and negative-control stacks.
- Full-volume confirmation and physical lumen geometry.
- Representative weak/medium/strong plug samples and one genuine 5–6 GB file.
- SME metric definitions and acceptance tolerances.
