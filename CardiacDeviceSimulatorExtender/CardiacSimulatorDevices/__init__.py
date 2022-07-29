try:
  import CardiacDeviceSimulator
except:
  import logging
  logging.info("CardiacDeviceSimulator (public SlicerHeart) has not been found. No cardiac device models will be loaded")
  pass