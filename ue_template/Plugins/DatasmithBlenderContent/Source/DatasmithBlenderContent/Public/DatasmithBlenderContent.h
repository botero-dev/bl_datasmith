// SPDX-FileCopyrightText: 2025 Andrés Botero
// SPDX-License-Identifier: MIT
// SPDX-FileName: DatasmithBlenderContent.h

#pragma once

#include "CoreMinimal.h"
#include "Modules/ModuleManager.h"

class FDatasmithBlenderContentModule : public IModuleInterface
{
public:

	/** IModuleInterface implementation */
	virtual void StartupModule() override;
	virtual void ShutdownModule() override;
};
