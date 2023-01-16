// Copyright Andrés Botero. All Rights Reserved.

#include "DatasmithBlenderContent.h"
#include "Misc/Paths.h"
#include "ShaderCore.h"

#define LOCTEXT_NAMESPACE "FDatasmithBlenderContentModule"

void FDatasmithBlenderContentModule::StartupModule()
{
	// This code will execute after your module is loaded into memory; the exact timing is specified in the .uplugin file per-module

	FString ShaderDir = FPaths::Combine(FPaths::ProjectPluginsDir(), TEXT("DatasmithBlenderContent/Shaders"));
	AddShaderSourceDirectoryMapping("/Plugin/DatasmithBlenderContent", ShaderDir);
}

void FDatasmithBlenderContentModule::ShutdownModule()
{
	// This function may be called during shutdown to clean up your module.  For modules that support dynamic reloading,
	// we call this function before unloading the module.
}

#undef LOCTEXT_NAMESPACE
	
IMPLEMENT_MODULE(FDatasmithBlenderContentModule, DatasmithBlenderContent)