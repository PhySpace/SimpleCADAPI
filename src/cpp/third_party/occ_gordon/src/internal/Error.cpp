/*
* SPDX-License-Identifier: Apache-2.0
* SPDX-FileCopyrightText: 2018 German Aerospace Center (DLR)
*
* Created: 2018-08-06 Martin Siggel <Martin.Siggel@dlr.de>
*/

#include "Error.h"

using namespace occ_gordon_internal;

// Constructor
error::error(std::string error, error_code errorCode) noexcept
    : err(error)
    , code(errorCode)
{
}

// Destructor
error::~error() noexcept
{
}

const char* error::what() const noexcept
{
    return err.c_str();
}

// Returns the error code
error_code error::get_code() const noexcept
{
    return code;
}
