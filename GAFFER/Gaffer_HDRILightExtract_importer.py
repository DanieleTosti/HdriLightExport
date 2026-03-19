import GafferScene
import GafferImage
import Gaffer, GafferUI
import IECore
import os, sys, time
import imath


def buildLightRig(scriptNode, lightType="usd"):
	"""
	Author: Daniele Tosti - 2026-03
	Gaffer HDRI Light Rig Importer  v2.15

	Converts Nuke's HDRI Light Export metadata into a Gaffer lighting rig.
	Select a GafferImage::ImageReader node pointing to an HDRI EXR with
	embedded metadata, then run this function to build the complete light rig.

	Features:
		- USD (DomeLight / RectLight / DistantLight) and Arnold light support
		- Per-light LightGroup metadata read from Nuke -> _LGT<n> naming
		- Enable_z_translate toggle + ZTranslate_lights offset (separate chain)
		- Exposure_compensation global control with per-light expressions
		- AimConstraint targeting the environment light
		- Per-light Transform + ZTransform nodes for manual adjustment
		- BoxIn/BoxOut passthrough for clean node bypass
		- Name sanitization (dashes replaced with underscores)

	Args:
		scriptNode: The Gaffer script node (usually 'root')
		lightType: "usd" (default) or "arnold"

	Usage:
		import importlib
		import Gaffer_HDRILightExtract_importer
		importlib.reload(Gaffer_HDRILightExtract_importer)
		Gaffer_HDRILightExtract_importer.buildLightRig(root)
		Gaffer_HDRILightExtract_importer.buildLightRig(root, "arnold")

	Author: DanieleT - 202106 (Vanilla port: 2026-03)
	"""

	if lightType == "arnold":
		import GafferArnold
		import GafferOSL
	else:
		import GafferUSD

	# Get user selection
	selection = scriptNode.selection()

	if not len(selection):
		print("Please select an ImageReader pointing to an HDRI generated from the HDRI Light Extract tool")
		return

	userSelectionNode = selection[0]

	if userSelectionNode.typeName() != "GafferImage::ImageReader":
		print("Please select a GafferImage::ImageReader node")
		return

	parent = userSelectionNode.parent()

	# Create metadata reader
	metadataNode = GafferImage.ImageMetadata("MetadataReader")
	parent.addChild(metadataNode)
	metadataNode["in"].setInput(userSelectionNode["out"])

	try:
		all_metadata = metadataNode["out"]["metadata"].getValue()
	except Exception as e:
		print("Failed to read metadata: {}".format(str(e)))
		parent.removeChild(metadataNode)
		return

	# Parse metadata
	lightsList = {}
	envLightName = ''

	for key in all_metadata.keys():
		if 'nuke/HDRI_CROP_Name' in key:
			envLightName = str(all_metadata[key].value)

		if "HDRI_CROP_LGT" in key:
			parts = key.split('_')
			lightName = None
			for i, part in enumerate(parts):
				if 'LGT' in part and i > 0:
					lightName = part
					break

			if lightName and lightName not in lightsList:
				lightsList[lightName] = {}

			if lightName:
				lightsList[lightName][key] = str(all_metadata[key].value)

	if not len(lightsList) or envLightName == '':
		print("No HDRI Light Extract metadata found")
		parent.removeChild(metadataNode)
		return

	parent.removeChild(metadataNode)

	# Sanitize env light name
	envLightName = envLightName.replace("-", "_")

	date = time.strftime("%Y%m%d%H%M%S")

	# Rename selection node to avoid conflicts on repeated runs
	userSelectionNode_name = userSelectionNode.getName()
	userSelectionNode.setName(userSelectionNode_name + "__" + date)

	box_label = "HDRI_RIG__" + envLightName + "__" + date
	box = Gaffer.Box(box_label)
	parent.addChild(box)
	box.addChild(userSelectionNode)

	# Create groups
	areaLightsGroup = GafferScene.Group("AERig_group")
	box.addChild(areaLightsGroup)
	areaLightsGroup["name"].setValue("AERig_group")
	areaLightsGroup["transform"]["scale"].setValue(imath.V3f(2, 2, 2))

	envLightsGroup = GafferScene.Group("ENV_group")
	box.addChild(envLightsGroup)
	envLightsGroup["name"].setValue("ENV_group")

	rigGroup = GafferScene.Group("HDRIRig_" + envLightName)
	box.addChild(rigGroup)
	rigGroup["name"].setValue("HDRIRig_" + envLightName)
	rigGroup["user"].addChild(
		Gaffer.FloatPlug(
			"Exposure_compensation",
			defaultValue=0.0,
			flags=Gaffer.Plug.Flags.Default | Gaffer.Plug.Flags.Dynamic
		)
	)
	rigGroup["user"].addChild(
		Gaffer.BoolPlug(
			"Enable_z_translate",
			defaultValue=False,
			flags=Gaffer.Plug.Flags.Default | Gaffer.Plug.Flags.Dynamic
		)
	)
	rigGroup["user"].addChild(
		Gaffer.FloatPlug(
			"ZTranslate_lights",
			defaultValue=0.0,
			flags=Gaffer.Plug.Flags.Default | Gaffer.Plug.Flags.Dynamic
		)
	)

	# Create environment light
	if lightType == "arnold":
		envLight = GafferArnold.ArnoldLight(envLightName)
		box.addChild(envLight)
		envLight.loadShader("skydome_light")

		envLight_textureNode = GafferOSL.OSLShader("Texture_" + envLightName)
		envLight_textureNode.loadShader("Texture/Texture")
		envLight["parameters"]["color"].setInput(envLight_textureNode["out"]["tex"])
		envLight_textureNode["parameters"]["filename"].setInput(userSelectionNode["fileName"])
		box.addChild(envLight_textureNode)
	else:
		envLight = GafferUSD.USDLight(envLightName)
		box.addChild(envLight)
		envLight.loadShader("DomeLight")

	envLight["name"].setValue('LGT0')
	envLight["transform"]["rotate"].setValue(imath.V3f(0, -90, 0))

	# Set HDRI texture on env light (Arnold handled above via texture node)
	if lightType == "usd":
		hdriPath = userSelectionNode["fileName"].getValue()
		try:
			envLight["parameters"]["texture:file"].setValue(hdriPath)
		except:
			print("Warning: Could not set texture:file on DomeLight")

	# Arnold lightgroup on env light
	if lightType == "arnold":
		try:
			envLight["parameters"]["aov"].setValue("lightGroup0")
		except:
			pass

	try:
		envLight["visualiserAttributes"]["scale"]["value"].setValue(22.0)
		envLight["visualiserAttributes"]["scale"]["enabled"].setValue(True)
	except:
		pass

	# Exposure expression for env light
	expression_node = Gaffer.Expression("exposureCompensation_expression_" + envLightName)
	box.addChild(expression_node)
	expression_node["__engine"].setValue('python')
	expression_node.setExpression(
		'parent["' + envLightName + '"]["parameters"]["exposure"] = '
		'parent["HDRIRig_' + envLightName + '"]["user"]["Exposure_compensation"]'
	)

	# Get base path from HDRI for texture path conversion
	hdriFilePath = userSelectionNode["fileName"].getValue()
	hdriBaseDir = os.path.dirname(hdriFilePath)

	# Create area/sun lights
	areaLights = []
	setName = 'light_set_' + envLightName
	lightGroup_counter = 2

	for light in lightsList:
		lightIsSun = 0.0
		lightLightGroup = ""
		prefix = "nuke/HDRI_CROP_" + light + "_"

		try:
			lightName = lightsList[light][prefix + 'Name']
			lightName = lightName.replace("-", "_")
			lightExtractModeType = lightsList[light][prefix + 'ExtractModeType']
			lightEV = float(lightsList[light][prefix + 'EV'])
			lightScale = eval(lightsList[light][prefix + 'Scale'])
			lightWidth = lightScale[0]
			lightHeight = lightScale[1]
			lightPosition = eval(lightsList[light][prefix + 'Pos3D'])
			lightTexture = lightsList[light].get(prefix + 'OutputPath', '')

			try:
				lightIsSun = float(lightsList[light][prefix + 'IsSun'])
			except:
				lightIsSun = 0.0

			try:
				lightLightGroup = lightsList[light][prefix + 'LightGroup']
			except:
				lightLightGroup = ""

		except Exception as e:
			print("Warning: Failed to parse light {}: {}".format(light, str(e)))
			continue

		base_exposure = lightEV / 4.0

		# Resolve texture path
		resolvedTexture = ''
		if lightTexture:
			textureFilename = os.path.basename(lightTexture.replace('//', '/').replace('\\', '/'))
			localTexturePath = os.path.join(hdriBaseDir, textureFilename)
			resolvedTexture = localTexturePath.replace('\\', '/')
			print("  Converting texture path: {} -> {}".format(lightTexture, resolvedTexture))

		if lightIsSun == 0.0:
			# Area light
			if lightType == "arnold":
				al = GafferArnold.ArnoldLight(lightName)
				box.addChild(al)
				al.loadShader("quad_light")

				if resolvedTexture:
					al_textureNode = GafferOSL.OSLShader("Texture_" + lightName)
					al_textureNode.loadShader("Texture/Texture")
					al["parameters"]["color"].setInput(al_textureNode["out"]["tex"])
					al_textureNode["parameters"]["filename"].setValue(resolvedTexture)
					box.addChild(al_textureNode)

				scale_divider = 15.0
				if lightExtractModeType == 'corner_pin':
					scale_divider = 25.0
				al["transform"]["scale"][0].setValue(lightHeight / scale_divider)
				al["transform"]["scale"][1].setValue(lightHeight / scale_divider)
			else:
				al = GafferUSD.USDLight(lightName)
				box.addChild(al)
				al.loadShader("RectLight")

			# Apply LightGroup naming
			lgVal = lightLightGroup if lightLightGroup else str(lightGroup_counter)
			al.setName(lightName + "_LGT" + lgVal)
			al["name"].setValue(lightName + "_LGT" + lgVal)
			lightName = lightName + "_LGT" + lgVal

			# Set lightgroup parameter per renderer
			if lightType == "arnold":
				try:
					al["parameters"]["aov"].setValue("lightGroup" + lgVal)
				except Exception as e:
					print("Warning: Could not set aov for {}: {}".format(lightName, e))
			else:
				try:
					al["parameters"]["cycles:lightgroup"]["enabled"].setValue(True)
					al["parameters"]["cycles:lightgroup"]["value"].setValue(lgVal)
				except Exception as e:
					print("Warning: Could not set lightgroup for {}: {}".format(lightName, e))

			areaLights.append(al)

			# Set size (USD uses width/height parameters; Arnold uses transform scale above)
			if lightType != "arnold":
				scale_divider = 15.0
				if lightExtractModeType == 'corner_pin':
					scale_divider = 25.0
				try:
					al["parameters"]["width"].setValue(lightWidth / scale_divider)
					al["parameters"]["height"].setValue(lightHeight / scale_divider)
				except Exception as e:
					print("Warning: Could not set width/height: {}".format(e))

			al["transform"]["translate"].setValue(
				imath.V3f(lightPosition[0], lightPosition[1], lightPosition[2])
			)

			# Set texture (USD uses texture:file; Arnold uses OSL node above)
			if resolvedTexture and lightType == "usd":
				try:
					al["parameters"]["texture:file"].setValue(resolvedTexture)
				except Exception as e:
					print("Warning: Could not set texture for {}: {}".format(lightName, e))

			try:
				al["parameters"]["exposure"].setValue(base_exposure)
			except:
				pass

			al["sets"].setValue(setName)

		else:
			# Sun/distant light
			if lightType == "arnold":
				dl = GafferArnold.ArnoldLight(lightName)
				box.addChild(dl)
				dl.loadShader("distant_light")
			else:
				dl = GafferUSD.USDLight(lightName)
				box.addChild(dl)
				dl.loadShader("DistantLight")

			# Apply LightGroup naming
			lgVal = lightLightGroup if lightLightGroup else str(lightGroup_counter)
			dl.setName(lightName + "_LGT" + lgVal)
			dl["name"].setValue(lightName + "_LGT" + lgVal)
			lightName = lightName + "_LGT" + lgVal

			# Set lightgroup parameter per renderer
			if lightType == "arnold":
				try:
					dl["parameters"]["aov"].setValue("lightGroup" + lgVal)
				except Exception as e:
					print("Warning: Could not set aov for {}: {}".format(lightName, e))
			else:
				try:
					dl["parameters"]["cycles:lightgroup"]["enabled"].setValue(True)
					dl["parameters"]["cycles:lightgroup"]["value"].setValue(lgVal)
				except Exception as e:
					print("Warning: Could not set lightgroup for {}: {}".format(lightName, e))

			areaLights.append(dl)

			dl["transform"]["translate"].setValue(
				imath.V3f(lightPosition[0], lightPosition[1], lightPosition[2])
			)

			try:
				dl["parameters"]["exposure"].setValue(base_exposure)
			except:
				pass

			dl["sets"].setValue(setName)

		# Exposure expression for this light
		expression_node = Gaffer.Expression("exposureCompensation_expression_" + lightName)
		box.addChild(expression_node)
		expression_node["__engine"].setValue('python')
		expression_node.setExpression(
			'parent["' + lightName + '"]["parameters"]["exposure"] = '
			'parent["HDRIRig_' + envLightName + '"]["user"]["Exposure_compensation"] + ' + str(base_exposure)
		)

		lightGroup_counter += 1

	# Connect lights to groups
	for n in range(len(areaLights)):
		areaLightsGroup['in'][n].setInput(areaLights[n]["out"])

	envLightsGroup['in'][0].setInput(envLight["out"])
	rigGroup['in'][0].setInput(envLightsGroup["out"])
	rigGroup['in'][1].setInput(areaLightsGroup["out"])

	# Setup aim constraint
	AimConstraint = GafferScene.AimConstraint("AimConstraint")
	setsFilter = GafferScene.SetFilter("SetsFilter")
	box.addChild(AimConstraint)
	box.addChild(setsFilter)
	AimConstraint["filter"].setInput(setsFilter["out"])
	AimConstraint["in"].setInput(rigGroup["out"])
	setsFilter["setExpression"].setValue(setName)

	p = hierarchyWalk(AimConstraint['out'], '/')
	for location_fullPath in p:
		if envLight['name'].getValue() in location_fullPath:
			AimConstraint["target"].setValue(location_fullPath)
			break

	# Per-light transform controls
	transform_nodes = []
	for light in areaLights:
		lightName = light.getName()

		transform_node = GafferScene.Transform("Transform_" + lightName)
		box.addChild(transform_node)
		pathFilter_node = GafferScene.PathFilter("PathFilter_" + lightName)
		box.addChild(pathFilter_node)

		full_paths = hierarchyWalk(AimConstraint['out'], '/')
		for location_fullPath in full_paths:
			if lightName == os.path.basename(location_fullPath):
				pathFilter_node["paths"].setValue(IECore.StringVectorData([location_fullPath]))
				break

		transform_node["filter"].setInput(pathFilter_node["out"])
		if len(transform_nodes) == 0:
			transform_node["in"].setInput(AimConstraint["out"])
		else:
			transform_node["in"].setInput(transform_nodes[-1]["out"])

		transform_nodes.append(transform_node)

	# Per-light ZTransform controls (separate chain, toggleable)
	ztransform_nodes = []
	for light in areaLights:
		lightName = light.getName()

		ztransform_node = GafferScene.Transform("ZTransform_" + lightName)
		box.addChild(ztransform_node)
		zpathFilter_node = GafferScene.PathFilter("ZPathFilter_" + lightName)
		box.addChild(zpathFilter_node)

		full_paths = hierarchyWalk(AimConstraint['out'], '/')
		for location_fullPath in full_paths:
			if lightName == os.path.basename(location_fullPath):
				zpathFilter_node["paths"].setValue(IECore.StringVectorData([location_fullPath]))
				break

		ztransform_node["filter"].setInput(zpathFilter_node["out"])
		if len(ztransform_nodes) == 0:
			if transform_nodes:
				ztransform_node["in"].setInput(transform_nodes[-1]["out"])
			else:
				ztransform_node["in"].setInput(AimConstraint["out"])
		else:
			ztransform_node["in"].setInput(ztransform_nodes[-1]["out"])

		# Enable expression driven by Enable_z_translate
		enable_expr = Gaffer.Expression("Enable_z_translate_expression_" + lightName)
		box.addChild(enable_expr)
		enable_expr["__engine"].setValue("python")
		enable_expr.setExpression(
			'parent["ZTransform_' + lightName + '"]["enabled"] = '
			'parent["HDRIRig_' + envLightName + '"]["user"]["Enable_z_translate"]'
		)

		# Z translate expression driven by ZTranslate_lights
		z_expr = Gaffer.Expression("ZTranslate_lights_expression_" + lightName)
		box.addChild(z_expr)
		z_expr["__engine"].setValue("python")
		z_expr.setExpression(
			'parent["ZTransform_' + lightName + '"]["transform"]["translate"]["z"] = '
			'parent["HDRIRig_' + envLightName + '"]["user"]["ZTranslate_lights"]'
		)

		ztransform_nodes.append(ztransform_node)

	# Final parent node
	parentNode = GafferScene.Parent("Parent")
	box.addChild(parentNode)

	if ztransform_nodes:
		parentNode["children"][0].setInput(ztransform_nodes[-1]["out"])
	elif transform_nodes:
		parentNode["children"][0].setInput(transform_nodes[-1]["out"])
	else:
		parentNode["children"][0].setInput(AimConstraint["out"])

	parentNode["parent"].setValue("/")
	Gaffer.BoxIO.promote(parentNode["in"])
	Gaffer.BoxIO.promote(parentNode["out"])
	Gaffer.BoxIO.promote(rigGroup['transform'])
	Gaffer.BoxIO.promote(rigGroup["user"]['Exposure_compensation'])
	Gaffer.BoxIO.promote(rigGroup["user"]['Enable_z_translate'])
	Gaffer.BoxIO.promote(rigGroup["user"]['ZTranslate_lights'])

	# BoxIn/BoxOut passthrough for clean node bypass
	boxIn = box.getChild("BoxIn")
	boxOut = box.getChild("BoxOut")
	boxOut["passThrough"].setInput(boxIn["out"])

	# Hide promoted user plugs from nodule display
	Gaffer.Metadata.registerValue(box["user_Exposure_compensation"], "nodule:type", "")
	Gaffer.Metadata.registerValue(box["user_Enable_z_translate"], "nodule:type", "")
	Gaffer.Metadata.registerValue(box["user_ZTranslate_lights"], "nodule:type", "")

	print("HDRI Light Rig created: {} with {} lights (using {} lights)".format(
		box_label, len(areaLights), lightType.upper()))


def hierarchyWalk(scene, path, maxDepth=10):
	hierarchy = []

	def recurse(scene, path, depth):
		if depth > maxDepth:
			return
		try:
			children = scene.childNames(path)
		except:
			return
		for childName in children:
			if path == '/':
				newPath = '/' + str(childName)
			else:
				newPath = path + '/' + str(childName)
			hierarchy.append(newPath)
			recurse(scene, newPath, depth + 1)

	recurse(scene, path, 0)
	return hierarchy
