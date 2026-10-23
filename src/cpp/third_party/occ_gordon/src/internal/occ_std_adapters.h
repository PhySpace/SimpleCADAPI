/*
* SPDX-License-Identifier: Apache-2.0
* SPDX-FileCopyrightText: 2024 German Aerospace Center (DLR)
*/

#ifndef OCC_STD_ADAPTERS_H
#define OCC_STD_ADAPTERS_H

#include <TColStd_HArray1OfReal.hxx>
#include <TColStd_HArray1OfInteger.hxx>
#include <TColgp_HArray1OfPnt.hxx>

#include <vector>

inline Handle(TColStd_HArray1OfReal) OccFArray(const std::vector<double>& vector)
{
    Handle(TColStd_HArray1OfReal) array = new TColStd_HArray1OfReal(1, static_cast<int>(vector.size()));
    int ipos = 1;
    for (const auto& value : vector) {
        array->SetValue(ipos, value);
        ipos++;
    }

    return array;
}


inline Handle(TColStd_HArray1OfInteger) OccIArray(const std::vector<int>& vector)
{
    Handle(TColStd_HArray1OfInteger) array = new TColStd_HArray1OfInteger(1, static_cast<int>(vector.size()));
    int ipos = 1;
    for (const auto& value : vector) {
        array->SetValue(ipos++, value);
    }

    return array;
}

/// Converters between std::vectors and opencascade vectors
inline Handle(TColgp_HArray1OfPnt) OccArray(const std::vector<gp_Pnt>& pnts)
{
    Handle(TColgp_HArray1OfPnt) result = new TColgp_HArray1OfPnt(1, static_cast<int>(pnts.size()));
    int idx = 1;
    for (std::vector<gp_Pnt>::const_iterator it = pnts.begin(); it != pnts.end(); ++it, ++idx) {
        result->SetValue(idx, *it);
    }
    return result;
}

#endif //  OCC_STD_ADAPTERS_H
