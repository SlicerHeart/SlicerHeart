# Valve Quantification module

## Summary

Valve Quantification module automatically computes 100+ metrics (lengths, distances, areas, volumes) from a valve annulus contour, landmarks, and leaflet segmentation. There are metrics specialized for the mitral, tricuspid, and CAVC.

![](../ValveQuantification/Resources/MeasurementPreset/MitralValve.png)

![](../ValveQuantification/Resources/MeasurementPreset/TricuspidValve.png)

![](../ValveQuantification/Resources/MeasurementPreset/Cavc.png)

## Usage

- Use Valve Annulus Analysis module to specify the annulus contour
- Use Valve Segmentation module to segment leaflets (optional)
- Go to Valve Quantification module, select the heart valve node and quantification preset
- Specify additional reference points (if necessary)
- Open `Output` section to compute quantification results

## References

Hannah H. Nam, Christian Herz, Andras Lasso, Alana Cianciulli, Maura Flynn, Jing Huang, Zi Wang, Beatriz Paniagua, Jared Vicory, Saleha Kabir, John Simpson, David Harrild, Gerald Marx, Meryl S. Cohen, Andrew C. Glatz, Matthew A. Jolley, "Visualization and Quantification of the Unrepaired Complete Atrioventricular Canal Valve using Open-Source Software", Journal of the American Society of Echocardiography, 2022, https://www.sciencedirect.com/science/article/abs/pii/S0894731722002334
