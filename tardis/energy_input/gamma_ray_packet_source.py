import astropy.units as u
import numpy as np

from tardis.energy_input.GXPacket import (
    GXPacketCollection,
)
from tardis.energy_input.samplers import (
    PositroniumSampler,
    sample_energy,
)
from tardis.energy_input.util import (
    H_CGS_KEV,
    doppler_factor_3d,
    doppler_factor_3D_all_packets,
    get_index,
    get_random_unit_vector,
)
from tardis.transport.montecarlo.packet_source import BasePacketSource

POSITRON_ANNIHILATION_LINE = 511.0
PARA_TO_ORTHO_RATIO = 0.25


class RadioactivePacketSource(BasePacketSource):
    def __init__(
        self,
        packet_energy,
        gamma_ray_lines,
        positronium_fraction,
        inner_velocities,
        outer_velocities,
        inv_volume_time,
        times,
        energy_df_rows,
        effective_times,
        taus,
        parents,
        average_positron_energies,
        average_power_per_mass,
        **kwargs,
    ):
        self.packet_energy = packet_energy
        self.gamma_ray_lines = gamma_ray_lines
        self.positronium_fraction = positronium_fraction
        self.inner_velocities = inner_velocities
        self.outer_velocities = outer_velocities
        self.inv_volume_time = inv_volume_time
        self.times = times
        self.energy_df_rows = energy_df_rows
        self.effective_times = effective_times
        self.taus = taus
        self.parents = parents
        self.average_positron_energies = average_positron_energies
        self.average_power_per_mass = average_power_per_mass
        self.energy_plot_positron_rows = np.empty(0)
        super().__init__(**kwargs)

    def create_packet_mus(self, no_of_packets, *args, **kwargs):
        return super().create_packet_mus(no_of_packets, *args, **kwargs)

    def create_packet_radii(
        self, no_of_packets, inner_velocity, outer_velocity
    ):
        """Initialize the random radii of packets in a shell

        Parameters
        ----------
        packet_count : int
            Number of packets in the shell
        inner_velocity : float
            Inner velocity of the shell
        outer_velocity : float
            Outer velocity of the shell

        Returns
        -------
        array
            Array of length packet_count of random locations in the shell
        """
        z = np.random.random(no_of_packets)
        initial_radii = (
            z * inner_velocity**3.0 + (1.0 - z) * outer_velocity**3.0
        ) ** (1.0 / 3.0)

        return initial_radii

    def create_packet_nus(
        self,
        no_of_packets,
        energy,
        intensity,
        positronium_fraction,
        positronium_energy,
        positronium_intensity,
    ):
        """Create an array of packet frequency-energies (i.e. E = h * nu)

        Parameters
        ----------
        no_of_packets : int
            Number of packets to produce frequency-energies for
        energy : One-dimensional Numpy Array, dtype float
            Array of frequency-energies to sample
        intensity : One-dimensional Numpy Array, dtype float
            Array of intensities to sample
        positronium_fraction : float
            The fraction of positrons that form positronium
        positronium_energy : array
            Array of positronium frequency-energies to sample
        positronium_intensity : array
            Array of positronium intensities to sample

        Returns
        -------
        array
            Array of sampled frequency-energies
        array
            Positron creation mask
        """
        nu_energies = np.zeros(no_of_packets)
        positrons = np.zeros(no_of_packets)
        zs = np.random.random(no_of_packets)
        for i in range(no_of_packets):
            nu_energies[i] = sample_energy(energy, intensity)
            # positron
            if nu_energies[i] == 511:
                # positronium formation 25% of the time if fraction is 1
                if zs[i] < positronium_fraction and np.random.random() < 0.25:
                    nu_energies[i] = sample_energy(
                        positronium_energy, positronium_intensity
                    )
                positrons[i] = 1

        return nu_energies, positrons

    def create_packet_directions(self, no_of_packets):
        """Create an array of random directions

        Parameters
        ----------
        no_of_packets : int
            Number of packets to produce directions for

        Returns
        -------
        array
            Array of direction vectors
        """
        directions = np.zeros((3, no_of_packets))
        for i in range(no_of_packets):
            directions[:, i] = get_random_unit_vector()

        return directions

    def create_packet_energies(self, no_of_packets, energy):
        """Create the uniform packet energy for a number of packets

        Parameters
        ----------
        no_of_packets : int
            Number of packets
        energy : float
            The packet energy

        Returns
        -------
        array
            Array of packet energies
        """
        return np.ones(no_of_packets) * energy

    def create_packet_times_uniform_time(self, no_of_packets, start, end):
        """Samples decay time uniformly (needs non-uniform packet energies)

        Parameters
        ----------
        no_of_packets : int
            Number of packets
        start : float
            Start time
        end : float
            End time

        Returns
        -------
        array
            Array of packet decay times
        """
        z = np.random.random(no_of_packets)
        decay_times = z * start + (1 - z) * end
        return decay_times

    def create_packet_times_uniform_energy(
        self,
        no_of_packets,
        start_tau,
        end_tau=0.0,
        decay_time_min=0.0,
        decay_time_max=0.0,
    ):
        """Samples the decay time from the mean lifetime of the isotopes

        Parameters
        ----------
        no_of_packets : int
            Number of packets
        start_tau : float
            Initial isotope mean lifetime
        end_tau : float, optional
            Ending mean lifetime, by default 0.0 for single decays
        decay_time_min : float, optional
            Minimum time to decay, by default 0.0
        decay_time_max : float, optional
            Maximum time to decay, by default 0.0

        Returns
        -------
        array
            Array of decay times
        """
        decay_times = np.ones(no_of_packets) * decay_time_min
        for i in range(no_of_packets):
            # rejection sampling
            while (decay_times[i] <= decay_time_min) or (
                decay_times[i] >= decay_time_max
            ):
                decay_times[i] = -start_tau * np.log(
                    np.random.random()
                ) - end_tau * np.log(np.random.random())
        return decay_times

    def calculate_energy_factors(self, no_of_packets, start_time, decay_times):
        """Calculates the factors that adjust the energy of packets emitted
        before the first time step and moves those packets to the earliest
        possible time

        Parameters
        ----------
        no_of_packets : int
            Number of packets
        start_time : float
            First time step
        decay_times : array
            Packet decay times

        Returns
        -------
        array
            Energy factors
        array
            Adjusted decay times
        """
        energy_factors = np.ones(no_of_packets)
        for i in range(no_of_packets):
            if decay_times[i] < start_time:
                energy_factors[i] = decay_times[i] / start_time
                decay_times[i] = start_time
        return energy_factors, decay_times

    def create_packets(self, decays_per_isotope, *args, **kwargs):
        """Initialize a collection of GXPacket objects for the simulation
        to operate on.

        Parameters
        ----------
        decays_per_isotope : array int64
            Number of decays per simulation shell per isotope

        Returns
        -------
        list
            List of GXPacket objects
        array
            Array of main output dataframe rows
        array
            Array of plotting output dataframe rows
        array
            Array of positron output dataframe rows
        """
        number_of_packets = decays_per_isotope.sum().sum()
        decays_per_shell = decays_per_isotope.sum().values

        locations = np.zeros((3, number_of_packets))
        directions = np.zeros((3, number_of_packets))
        packet_energies_rf = np.zeros(number_of_packets)
        packet_energies_cmf = np.zeros(number_of_packets)
        nus_rf = np.zeros(number_of_packets)
        nus_cmf = np.zeros(number_of_packets)
        shells = np.zeros(number_of_packets)
        times = np.zeros(number_of_packets)
        # set packets to IN_PROCESS status
        statuses = np.ones(number_of_packets, dtype=np.int64) * 3

        positronium_energy, positronium_intensity = positronium_continuum()

        self.energy_plot_positron_rows = np.zeros((number_of_packets, 4))

        packet_index = 0
        # go through each shell
        for shell_number, pkts in enumerate(decays_per_shell):
            isotope_packet_count_df = decays_per_isotope.T.iloc[shell_number]

            for isotope_name, isotope_packet_count in zip(
                self.gamma_ray_lines.keys(), isotope_packet_count_df.values
            ):
                isotope_energy = self.gamma_ray_lines[isotope_name][0, :]
                isotope_intensity = self.gamma_ray_lines[isotope_name][1, :]
                isotope_positron_fraction = self.calculate_positron_fraction(
                    self.average_positron_energies[isotope_name],
                    isotope_energy,
                    isotope_intensity,
                )
                tau_start = self.taus[isotope_name]

                if isotope_name in self.parents:
                    tau_end = self.taus[self.parents[isotope_name]]
                else:
                    tau_end = 0

                # sample radii at time = 0
                initial_radii = self.create_packet_radii(
                    isotope_packet_count,
                    self.inner_velocities[shell_number],
                    self.outer_velocities[shell_number],
                )

                # sample directions (valid at all times)
                initial_directions = self.create_packet_directions(
                    isotope_packet_count
                )

                # packet decay time
                initial_times = self.create_packet_times_uniform_energy(
                    isotope_packet_count,
                    tau_start,
                    tau_end,
                    decay_time_min=0,
                    decay_time_max=self.times[-1],
                )

                # get the time step index of the packets
                initial_time_indexes = np.array(
                    [
                        get_index(decay_time, self.times)
                        for decay_time in initial_times
                    ]
                )

                # get the time of the middle of the step for each packet
                packet_effective_times = np.array(
                    [self.effective_times[i] for i in initial_time_indexes]
                )

                # scale radius by packet decay time. This could be replaced with
                # Geometry object calculations. Note that this also adds a random
                # unit vector multiplication for 3D. May not be needed.
                initial_locations = (
                    initial_radii
                    * packet_effective_times
                    * self.create_packet_directions(isotope_packet_count)
                )

                # get the packet shell index
                initial_shells = np.ones(isotope_packet_count) * shell_number

                # the individual gamma-ray energies that make up a packet
                # co-moving frame, including positronium formation
                initial_nu_energies_cmf, positron_mask = self.create_packet_nus(
                    isotope_packet_count,
                    isotope_energy,
                    isotope_intensity,
                    self.positronium_fraction,
                    positronium_energy,
                    positronium_intensity,
                )

                # equivalent frequencies
                initial_nus_cmf = initial_nu_energies_cmf / H_CGS_KEV

                # compute scaling factor for packets emitted before start time
                # and move packets to start at that time
                # probably not necessary- we have rejection sampling in the
                # create_packet_times_uniform_energy method
                energy_factors, initial_times = self.calculate_energy_factors(
                    isotope_packet_count, self.times[0], initial_times
                )

                # the CMF energy of a packet scaled by the "early energy factor"
                initial_packet_energies_cmf = (
                    self.create_packet_energies(
                        isotope_packet_count, self.packet_energy
                    )
                    * energy_factors
                )

                # rest frame gamma-ray energy and frequency
                # this probably works fine without the loop
                initial_packet_energies_rf = np.zeros(isotope_packet_count)
                initial_nus_rf = np.zeros(isotope_packet_count)
                for i in range(isotope_packet_count):
                    doppler_factor = doppler_factor_3d(
                        initial_directions[:, i],
                        initial_locations[:, i],
                        initial_times[i],
                    )
                    initial_packet_energies_rf[i] = (
                        initial_packet_energies_cmf[i] / doppler_factor
                    )
                    initial_nus_rf[i] = initial_nus_cmf[i] / doppler_factor

                    self.energy_plot_positron_rows[i] = np.array(
                        [
                            packet_index,
                            isotope_positron_fraction * self.packet_energy,
                            # * inv_volume_time[packet.shell, decay_time_index],
                            initial_radii[i],
                            initial_times[i],
                        ]
                    )

                    packet_index += 1

                # deposit positron energy
                for time in initial_time_indexes:
                    self.energy_df_rows[shell_number, time] += (
                        isotope_positron_fraction * self.packet_energy
                    )

                # collect packet properties
                locations[
                    :, packet_index - isotope_packet_count : packet_index
                ] = initial_locations
                directions[
                    :, packet_index - isotope_packet_count : packet_index
                ] = initial_directions
                packet_energies_rf[
                    packet_index - isotope_packet_count : packet_index
                ] = initial_packet_energies_rf
                packet_energies_cmf[
                    packet_index - isotope_packet_count : packet_index
                ] = initial_packet_energies_cmf
                nus_rf[
                    packet_index - isotope_packet_count : packet_index
                ] = initial_nus_rf
                nus_cmf[
                    packet_index - isotope_packet_count : packet_index
                ] = initial_nus_cmf
                shells[
                    packet_index - isotope_packet_count : packet_index
                ] = initial_shells
                times[
                    packet_index - isotope_packet_count : packet_index
                ] = initial_times

        return GXPacketCollection(
            locations,
            directions,
            packet_energies_rf,
            packet_energies_cmf,
            nus_rf,
            nus_cmf,
            statuses,
            shells,
            times,
        )

    def calculate_positron_fraction(
        self, positron_energy, isotope_energy, isotope_intensity
    ):
        """Calculate the fraction of energy that an isotope
        releases as positron kinetic energy

        Parameters
        ----------
        positron_energy : float
            Average kinetic energy of positrons from decay
        isotope_energy : numpy array
            Photon energies released by the isotope
        isotope_intensity : numpy array
            Intensity of photon energy release

        Returns
        -------
        float
            Fraction of energy released as positron kinetic energy
        """
        return positron_energy / np.sum(isotope_energy * isotope_intensity)


class GammaRayPacketSource(BasePacketSource):
    def __init__(
        self,
        packet_energy,
        isotope_decay_df,
        positronium_fraction,
        inner_velocities,
        outer_velocities,
        inv_volume_time,
        times,
        effective_times,
        taus,
        parents,
        **kwargs,
    ):
        """
        New Gamma ray packet source class

        Parameters
        ----------
        packet_energy : float
            Energy of the gamma ray packet
        isotope_decay_df : pd.DataFrame
            DataFrame of isotope decay data
        positronium_fraction : float
            Fraction of positrons that form positronium
        inner_velocities : array
            Array of inner shell velocities
        outer_velocities : array
            Array of outer shell velocities
        inv_volume_time : array
            Array of inverse volume times
            1 / ((4 * np.pi)/3 * (vt) ** 3)
            Indicates how the ejecta volume changes with time
        times : array
            Array of time steps
        effective_times : array
            Array of effective time steps
        taus : dict
            Dictionary of isotope mean lifetimes in seconds
        parents : dict
            Dictionary of isotope parents

        """
        self.packet_energy = packet_energy
        self.isotope_decay_df = isotope_decay_df
        self.positronium_fraction = positronium_fraction
        self.inner_velocities = inner_velocities
        self.outer_velocities = outer_velocities
        self.inv_volume_time = inv_volume_time
        self.times = times
        self.effective_times = effective_times
        self.taus = taus
        self.parents = parents
        super().__init__(**kwargs)

    def create_packet_mus(self, no_of_packets, *args, **kwargs):
        return super().create_packet_mus(no_of_packets, *args, **kwargs)

    def create_packet_radii(self, sampled_packets_df):
        """Initialize the random radii of packets in a shell

        Parameters
        ----------
        packet_count : int
            Number of packets in the shell
        sampled_packets_df : pd.DataFrame
            Dataframe where each row is a packet

        Returns
        -------
        array
            Array of length packet_count of random locations in the shell
        """
        z = np.random.random(len(sampled_packets_df))
        initial_radii = (
            z * sampled_packets_df["inner_velocity"] ** 3.0
            + (1.0 - z) * sampled_packets_df["outer_velocity"] ** 3.0
        ) ** (1.0 / 3.0)

        return initial_radii

    def create_packet_nus(
        self,
        packets,
        positronium_fraction,
        number_of_packets,
    ):
        """Create an array of packet frequency-energies (i.e. E = h * nu)

        Parameters
        ----------
        no_of_packets : int
            Number of packets to produce frequency-energies for
        packets : pd.DataFrame
            DataFrame of packets
        positronium_fraction : float
            The fraction of positrons that form positronium
            default is 0.0

        Returns
        -------
        array
            Array of sampled frequency-energies
        """
        energy_array = np.zeros(number_of_packets)

        all_packets = np.array([True] * number_of_packets)

        # positronium formation if fraction is greater than zero
        positronium_formation = (
            np.random.uniform(0, 1, number_of_packets) < positronium_fraction
        )
        # annihilation line of positrons
        annihilation_line = packets["radiation_energy_keV"] == POSITRON_ANNIHILATION_LINE
        # three photon decay of positronium
        three_photon_decay = np.random.random(number_of_packets) > PARA_TO_ORTHO_RATIO

        energy_array[all_packets] = packets.loc[
            all_packets, "radiation_energy_keV"
        ]

        energy_array[
            positronium_formation & annihilation_line & three_photon_decay
        ] = PositroniumSampler().sample_energy(
            samples=np.sum(
                positronium_formation & annihilation_line & three_photon_decay
            )
        )
        energy_array[
            positronium_formation & annihilation_line & ~three_photon_decay
        ] = POSITRON_ANNIHILATION_LINE

        return energy_array

    def create_packet_directions(self, no_of_packets):
        """Create an array of random directions

        Parameters
        ----------
        no_of_packets : int
            Number of packets to produce directions for

        Returns
        -------
        array
            Array of direction vectors
        """
        directions = np.zeros((3, no_of_packets))
        for i in range(no_of_packets):
            directions[:, i] = get_random_unit_vector()

        return directions

    def create_packet_energies(self, no_of_packets, energy):
        """Create the uniform packet energy for a number of packets

        Parameters
        ----------
        no_of_packets : int
            Number of packets
        energy : float
            The packet energy

        Returns
        -------
        array
            Array of packet energies
        """
        return np.ones(no_of_packets) * energy

    def create_packet_times_uniform_time(self, no_of_packets, start, end):
        """Samples decay time uniformly (needs non-uniform packet energies)

        Parameters
        ----------
        no_of_packets : int
            Number of packets
        start : float
            Start time
        end : float
            End time

        Returns
        -------
        array
            Array of packet decay times
        """
        z = np.random.random(no_of_packets)
        decay_times = z * start + (1 - z) * end
        return decay_times

    def create_packet_times_uniform_energy(
        self, no_of_packets, isotopes, decay_time
    ):
        """Samples the decay time from the mean lifetime of the isotopes

        Parameters
        ----------
        no_of_packets : int
            Number of packets
        isotopes : pd.Series
            Series of packet parent isotopes
        decay_time : array
            Series of packet decay time index

        Returns
        -------
        array
            Array of decay times
        """
        decay_times = np.zeros(len(no_of_packets))
        for i, isotope in enumerate(isotopes.to_numpy()):
            decay_time_min = self.times[decay_time[i]]
            if decay_time_min == self.times[-1]:
                decay_time_max = self.effective_times[-1]
            else:
                decay_time_max = self.times[decay_time[i] + 1]
            # rejection sampling
            while (decay_times[i] <= decay_time_min) or (
                decay_times[i] >= decay_time_max
            ):
                decay_times[i] = -self.taus[isotope] * np.log(
                    np.random.random()
                )
        return decay_times

    def create_packets(
        self, decays_per_isotope, number_of_packets, *args, **kwargs
    ):
        """Initialize a collection of GXPacket objects for the simulation
        to operate on.

        Parameters
        ----------
        decays_per_isotope : array int64
            Probability of decays per simulation shell per isotope per time step
        number_of_packets : int
            Number of packets to create

        Returns
        -------
        GXPacketCollection
        """
        # initialize arrays for most packet properties
        locations = np.zeros((3, number_of_packets))
        directions = np.zeros((3, number_of_packets))
        packet_energies_rf = np.zeros(number_of_packets)
        packet_energies_cmf = np.zeros(number_of_packets)
        nus_rf = np.zeros(number_of_packets)
        nus_cmf = np.zeros(number_of_packets)
        statuses = np.ones(number_of_packets, dtype=np.int64) * 3

        # sample packets from the gamma-ray lines only (include X-rays!)
        sampled_packets_df_gamma = decays_per_isotope[
            decays_per_isotope["radiation"] == "g"
        ]

        # sample packets from the time evolving dataframe
        sampled_packets_df = sampled_packets_df_gamma.sample(
            n=number_of_packets,
            weights="decay_energy_erg",
            replace=True,
            random_state=np.random.RandomState(self.base_seed),
        )

        # get the isotopes and shells of the sampled packets
        isotopes = sampled_packets_df.index.get_level_values("isotope")
        isotope_positron_fraction = self.calculate_positron_fraction(
            isotopes, number_of_packets
        )
        shells = sampled_packets_df.index.get_level_values("shell_number")

        # get the inner and outer velocity boundaries for each packet to compute
        sampled_packets_df["inner_velocity"] = self.inner_velocities[shells]
        sampled_packets_df["outer_velocity"] = self.outer_velocities[shells]

        # The radii of the packets at what ever time they are emitted
        initial_radii = self.create_packet_radii(sampled_packets_df)

        # get the time step index of the packets
        decay_time_indices = sampled_packets_df.index.get_level_values("time_index")

        effective_decay_times = self.times[decay_time_indices]

        # scale radius by packet decay time. This could be replaced with
        # Geometry object calculations. Note that this also adds a random
        # unit vector multiplication for 3D. May not be needed.
        locations = (
            initial_radii.values
            * effective_decay_times
            * self.create_packet_directions(number_of_packets)
        )

        # sample directions (valid at all times), non-relativistic
        directions = self.create_packet_directions(number_of_packets)

        # the individual gamma-ray energy that makes up a packet
        # co-moving frame, including positronium formation
        nu_energies_cmf = self.create_packet_nus(
            sampled_packets_df,
            self.positronium_fraction,
            number_of_packets,
        )

        nus_cmf = nu_energies_cmf / H_CGS_KEV

        packet_energies_cmf = self.create_packet_energies(
            number_of_packets, self.packet_energy
        )
        packet_energies_rf = np.zeros(number_of_packets)
        nus_rf = np.zeros(number_of_packets)

        doppler_factors = doppler_factor_3D_all_packets(
            directions, locations, effective_decay_times
        )

        packet_energies_rf = packet_energies_cmf / doppler_factors
        nus_rf = nus_cmf / doppler_factors

        return GXPacketCollection(
            locations,
            directions,
            packet_energies_rf,
            packet_energies_cmf,
            nus_rf,
            nus_cmf,
            statuses,
            shells,
            effective_decay_times,
            decay_time_indices,
        ), isotope_positron_fraction

    def calculate_positron_fraction(self, isotopes, number_of_packets):
        """Calculate the fraction of energy that an isotope
        releases as positron kinetic energy compared to gamma-ray energy

        Parameters
        ----------
        isotopes : array
            Array of isotope names as strings. Here each isotope is associated with a packet.
        number_of_packets : int
            Number of gamma-ray packets

        Returns
        -------
        dict
            Fraction of energy released as positron kinetic energy per isotope
        """
        isotope_positron_fraction = np.zeros(number_of_packets)

        # Find the positron fraction from the zeroth shell of the dataframe
        # this is because the total positron kinetic energy is the same for all shells
        shell_number_0 = self.isotope_decay_df[
            self.isotope_decay_df.index.get_level_values("shell_number") == 0
        ]

        gamma_decay_df = shell_number_0[shell_number_0["radiation"] == "g"]

        positrons_decay_df = shell_number_0[shell_number_0["radiation"] == "bp"]
        # Find the total energy released from positrons per isotope from the dataframe
        positron_energy_per_isotope = positrons_decay_df.groupby("isotope")[
            "energy_per_channel_keV"
        ].sum()
        # Find the total energy released from gamma-ray per isotope from the dataframe
        # TODO: Can be tested with total energy released from all radiation types
        gamma_energy_per_isotope = gamma_decay_df.groupby("isotope")[
            "energy_per_channel_keV"
        ].sum()
        # TODO: Possibly move this for loop
        for i, isotope in enumerate(isotopes):
            if isotope in positron_energy_per_isotope: # check if isotope is in the dataframe
                isotope_positron_fraction[i] = (
                    positron_energy_per_isotope[isotope]
                    / gamma_energy_per_isotope[isotope]
                )
        return isotope_positron_fraction
